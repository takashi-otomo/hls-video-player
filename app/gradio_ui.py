"""Gradio Blocks UI。動画一覧（カード/リスト）、アップロード、変換、進捗、
再生（Video.js 埋込）を担う。Phase 2 のメインモジュール。"""

from __future__ import annotations

import html
import logging
import os
import shutil
from pathlib import Path
from typing import Generator

import gradio as gr

_ui_logger = logging.getLogger(__name__)

from hls_video.config import max_concurrent_jobs, media_root, staging_dir
from hls_video.conversion_runner import run_conversion
from hls_video.drive_browser import (
    import_file, list_pending_staging, list_videos_under, stage_to_local,
)
from hls_video.job_registry import Job, JobRegistry
from hls_video.logging_setup import setup_logging
from hls_video.source_catalog import (
    delete_source_file, list_sources, resolve_video_id, VIDEO_EXTS,
)

from app.player_embed import empty_html, iframe_html


# Drive ブラウズ UI のデフォルトパス。Colab 上では /content/drive/MyDrive を、
# ローカルでは環境変数 DRIVE_BROWSE_ROOT か ./media/source を使う。
_DEFAULT_BROWSE_ROOT = os.environ.get(
    "DRIVE_BROWSE_ROOT",
    "/content/drive/MyDrive" if os.path.isdir("/content/drive/MyDrive") else "./",
)


# カードサムネイルと進捗表示用。Gradio のテーマと共存させるため名前空間を切る。
_CSS = """
.hls-card-thumb-wrap {
  position: relative;
  width: 100%;
  padding-top: 56.25%; /* 16:9 aspect via padding-bottom trick（Gradio 環境で aspect-ratio が効かないケースの対策） */
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #272c36;
  background-color: #0a0c10;
}
.hls-card-thumb {
  position: absolute;
  top: 0; left: 0;
  width: 100%;
  height: 100%;
  background-repeat: no-repeat;
  background-position: 0 0;
}
.hls-card-thumb--placeholder {
  background: repeating-linear-gradient(45deg, #0a0c10 0 10px, #14171f 10px 20px);
}
/* Drive 走査の CheckboxGroup は 10 件を超えたらスクロール。
   Gradio 6 では内側 .wrap がチェックボックス一覧のフレックスコンテナなので
   そこに max-height を付ける。ラベル部分は対象外に残す。 */
.hls-file-picker .wrap {
  max-height: 360px;
  overflow-y: auto;
  padding-right: 4px;
}
"""


# ---------------------------------------------------------------------------
# モデル関数（UI から呼ばれる純粋な関数群）
# ---------------------------------------------------------------------------

def _load_sources(media_dir: Path, registry: JobRegistry) -> list[dict]:
    """動画一覧 UI に渡す sources を作る。

    各行に `job_snapshot` と `_tick_at` を埋め込むことが重要:
      - Gradio の `gr.State` / `@gr.render` は入力値が「変わった」ときだけ
        再描画する。`sources` dict が毎 tick 同じ内容に見えると、
        バックエンドで job.progress が更新されていても UI が動かない。
      - snapshot() は progress / stage / last_progress_at を含むので、
        変換中は毎 tick 値が変わる。
      - さらに保険として `_tick_at` を増やし、どのポーリングでも必ず
        「値が違う」と Gradio に認識させる。
    """
    import time as _time
    tick = _time.time()
    sources = list_sources(str(media_dir))
    seen_vids: set[str] = set()
    for s in sources:
        active = registry.find_active_by_video_id(s["video_id"])
        if active:
            s["active_job_id"] = active.id
            s["job_snapshot"] = active.snapshot()
        else:
            s["active_job_id"] = None
            s["job_snapshot"] = None
        s["_tick_at"] = tick
        seen_vids.add(s["video_id"])

    # Drive ステージ経由の変換のように、source/ にも hls/ にもまだファイルが
    # 存在しない pending/running ジョブの仮想行を合成。
    for job in registry.list():
        if job.state not in ("pending", "running"):
            continue
        if job.video_id in seen_vids:
            continue
        sources.append({
            "filename": job.source_file or f"{job.video_id}.mp4",
            "video_id": job.video_id,
            "size_bytes": 0,
            "modified_at": job.created_at or "",
            "converted": False,
            "sprite": None,
            "source_deleted": True,   # ローカル実体なし扱い（サイズ欄に "—"）
            "active_job_id": job.id,
            "job_snapshot": job.snapshot(),
            "_tick_at": tick,
        })
        seen_vids.add(job.video_id)

    # ランタイム再起動などで JobRegistry が失われたが、Colab ローカル SSD の
    # staging 領域にはまだファイルが残っているケースを「再開待ち」として
    # 合成する。hls/<id>/master.m3u8 が存在しないもののみ対象。
    for p in list_pending_staging(str(staging_dir()), str(media_dir)):
        if p["video_id"] in seen_vids:
            continue
        from datetime import datetime as _dt, timezone as _tz
        sources.append({
            "filename": p["filename"],
            "video_id": p["video_id"],
            "size_bytes": p["size_bytes"],
            "modified_at": _dt.fromtimestamp(p["mtime"], tz=_tz.utc).isoformat(),
            "converted": False,
            "sprite": None,
            "source_deleted": False,
            "active_job_id": None,
            "job_snapshot": None,
            "pending_staging": True,
            "staged_path": p["path"],
            "_tick_at": tick,
        })
        seen_vids.add(p["video_id"])

    return sorted(sources, key=lambda r: r["filename"])


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    v = n / 1024.0
    for unit in ["KB", "MB", "GB"]:
        if v < 1024.0:
            return f"{v:.1f} {unit}" if v < 10 else f"{v:.0f} {unit}"
        v /= 1024.0
    return f"{v:.1f} TB"


def _thumb_html(sprite: dict | None) -> str:
    if sprite and sprite.get("sheets"):
        url = sprite["sheets"][0]
        cols = sprite.get("columns") or 10
        rows = sprite.get("rows") or 10
        style = (
            f"background-image:url('{html.escape(url)}');"
            f"background-size:{cols * 100}% {rows * 100}%;"
            f"background-position:0 0;"
        )
        return f'<div class="hls-card-thumb-wrap"><div class="hls-card-thumb" style="{style}"></div></div>'
    return '<div class="hls-card-thumb-wrap"><div class="hls-card-thumb hls-card-thumb--placeholder"></div></div>'


def _status_badge(source: dict, job: Job | None) -> str:
    if job and job.state in {"pending", "running"}:
        stage = {"probe": "解析中", "hls": "HLS変換中", "sprite": "サムネイル生成中"}.get(job.stage or "", "処理中")
        pct = int((job.progress or 0) * 100)
        bar = (
            f'<div style="width:100%;background:#13171e;border:1px solid #272c36;'
            f'border-radius:999px;height:8px;overflow:hidden;">'
            f'<div style="width:{pct}%;height:100%;background:linear-gradient(90deg,#4aa8ff,#6fd0ff);"></div></div>'
        )
        # 最終更新からの経過秒数を表示（stall 検出用）
        tail = ""
        if job.last_progress_at:
            from datetime import datetime, timezone
            try:
                last = datetime.fromisoformat(job.last_progress_at.replace("Z", "+00:00"))
                delta = (datetime.now(tz=timezone.utc) - last).total_seconds()
                if delta > 30:
                    color = "#ff9595" if delta > 120 else "#f0c47a"
                    tail = f' <span style="color:{color}">⚠ {int(delta)}s 更新なし</span>'
                else:
                    tail = f' <span style="color:#8b93a1">({int(delta)}s 前更新)</span>'
            except Exception:
                pass
        return f'<div>{bar}<div style="font-size:0.75rem;color:#8b93a1;margin-top:2px">{stage} <strong>{pct}%</strong>{tail}</div></div>'
    if job and job.state == "failed":
        return f'<span style="color:#ff9595">✗ 失敗: {html.escape((job.error or "")[:80])}</span>'
    if source.get("converted"):
        if source.get("source_deleted"):
            return '<span style="color:#7fd498">✓ 変換済</span> <span style="color:#8b93a1;font-size:0.75rem">(MP4 削除済)</span>'
        return '<span style="color:#7fd498">✓ 変換済</span>'
    if source.get("pending_staging"):
        return ('<span style="color:#6fd0ff">▶ 再開待ち</span>'
                ' <span style="color:#8b93a1;font-size:0.75rem">(ローカル staging にあり)</span>')
    return '<span style="color:#f0c47a">未変換</span>'


# ---------------------------------------------------------------------------
# UI 構築
# ---------------------------------------------------------------------------

def _save_upload(upload_path: str | None, media_dir: Path) -> str:
    if not upload_path:
        return "ファイルが選択されていません。"
    src = Path(upload_path)
    if src.suffix.lower() not in VIDEO_EXTS:
        return f"対応外の拡張子です（{', '.join(sorted(VIDEO_EXTS))}）"
    dest = media_dir / "source" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.resolve() == src.resolve():
        return f"{src.name} は既に配置済みです。"
    shutil.copy2(src, dest)
    return f"{src.name} を追加しました。"


def build_ui(
    *,
    media_dir: Path | None = None,
    registry: JobRegistry | None = None,
) -> gr.Blocks:
    # build_ui は Colab ノートブック側からも呼ばれる（app.main を通らない）ので、
    # どの経路でも stdout に INFO ログが出るようここで初期化する。
    setup_logging()

    media_dir = media_dir or media_root()
    registry = registry or JobRegistry(max_workers=max_concurrent_jobs())

    # ディレクトリは起動時に必ず用意しておく（アップロード保存先）
    for sub in ("source", "hls", "sprites"):
        (media_dir / sub).mkdir(parents=True, exist_ok=True)

    with gr.Blocks(title="HLS Video Library") as demo:
        # Gradio 6 では Blocks(css=...) が効かないため、style タグを直接注入する
        gr.HTML(f"<style>{_CSS}</style>")
        gr.Markdown("## HLS Video Library\nMP4 → HLS アダプティブストリーミング / シークバーサムネイル対応")

        # state
        sources_state = gr.State([])  # list[dict] as returned by _load_sources
        view_mode_state = gr.State("list")  # デフォルトをリスト表示に
        playing_state = gr.State(None)  # video_id | None
        sort_state = gr.State({"column": "filename", "direction": "asc"})

        # --- 動画の追加エリア (Drive browse + ローカルアップロード) ---
        with gr.Row():
            with gr.Column(scale=3):
                with gr.Tabs():
                    with gr.Tab("Drive / サーバから追加"):
                        gr.Markdown(
                            "指定したディレクトリ配下の `.mp4 / .mov / .mkv / .webm` を走査し、"
                            "**複数選択 → キュー投入** で順次変換します。\n"
                            "- ファイルは一度 `/tmp` (Colab ローカル SSD) にコピーしてから変換\n"
                            "- 変換先は `media/hls/`, `media/sprites/`（Drive 配下）\n"
                            "- 同時実行数は `MAX_CONCURRENT_JOBS` env で制御（既定 2）\n"
                            "- ✓ [重複] が付く動画: 既に変換済み / または `media/source/` に同名あり（キュー投入時にスキップ）"
                        )
                        with gr.Row():
                            browse_path = gr.Textbox(
                                value=_DEFAULT_BROWSE_ROOT,
                                label="走査するディレクトリパス",
                                scale=4,
                            )
                            scan_btn = gr.Button("🔍 走査", scale=1)
                        sort_by = gr.Radio(
                            choices=[
                                ("ファイル名", "name"),
                                ("サイズ(大→小)", "size"),
                                ("更新日時(新→旧)", "mtime"),
                            ],
                            value="name",
                            label="並び順",
                            container=False,
                        )
                        file_picker = gr.CheckboxGroup(
                            choices=[],
                            label="変換対象（複数選択可、10 件超はスクロール）",
                            interactive=True,
                            elem_classes=["hls-file-picker"],
                        )
                        entries_state = gr.State([])           # list[BrowseEntry]
                        with gr.Row():
                            convert_btn = gr.Button("🎬 選択ぶんをキューに追加", variant="primary")
                            select_all_btn = gr.Button("全選択", variant="secondary")
                            clear_sel_btn = gr.Button("選択解除", variant="secondary")
                        browse_msg = gr.Markdown(visible=False)
                    with gr.Tab("PC からアップロード"):
                        gr.Markdown(
                            "_PC 上のファイルを直接 Colab へアップロードします。Drive 上にあるものは "
                            "「Drive / サーバから追加」のタブを使った方が通信量を節約できます。_"
                        )
                        upload = gr.File(
                            label="動画を追加（.mp4 / .mov / .mkv / .webm）",
                            file_types=[f"*{ext}" for ext in VIDEO_EXTS],
                            type="filepath",
                        )
                        upload_msg = gr.Markdown(visible=False)

        # プレイヤー領域
        player_area = gr.HTML(value=empty_html(), label="プレイヤー")

        # 進行中ジョブがあるときだけ 1.5 秒間隔で sources を再読込するポーリング Timer
        poll_timer = gr.Timer(1.5, active=False)

        # --- 動画一覧ヘッダ: 表示切替と更新ボタンを一覧の直上に配置 ---
        with gr.Row():
            gr.Markdown("### 動画一覧")
            with gr.Column(scale=0, min_width=320):
                with gr.Row():
                    view_mode = gr.Radio(
                        choices=[("≡ リスト", "list"), ("▦ カード", "card")],
                        value="list",
                        label=None,
                        show_label=False,
                        container=False,
                        scale=2,
                    )
                    refresh_btn = gr.Button("↻ 更新", size="sm", scale=1)

        # 動画一覧（動的再描画）
        @gr.render(inputs=[sources_state, view_mode_state, sort_state])
        def draw_library(sources: list[dict], mode: str, sort_cfg: dict):
            if not sources:
                gr.Markdown("_media/source/ にファイルがありません。「Drive / サーバから追加」か「PC からアップロード」でファイルを追加してください。_")
                return

            if mode == "list":
                _render_list(
                    _sort_sources(sources, sort_cfg),
                    registry, sources_state, playing_state, player_area, poll_timer,
                    sort_cfg, sort_state,
                )
            else:
                _render_cards(sources, registry, sources_state, playing_state, player_area, poll_timer)

        # --- Events ---

        def _refresh():
            sources = _load_sources(media_dir, registry)
            any_active = any(s.get("active_job_id") for s in sources)
            # Colab でトンネル経由の Timer 挙動が怪しいときの切り分け用。
            # アクティブなジョブがある間だけ INFO に上げる（進行中しか UI 更新が
            # 重要ではないので、アイドル時のノイズは DEBUG に抑える）。
            level = logging.INFO if any_active else logging.DEBUG
            snapshots = [
                (s.get("video_id"),
                 (s.get("job_snapshot") or {}).get("stage"),
                 round((s.get("job_snapshot") or {}).get("progress") or 0, 3))
                for s in sources if s.get("active_job_id")
            ]
            _ui_logger.log(level, "UI refresh: %d sources, active=%s %s",
                           len(sources), any_active, snapshots)
            return sources, gr.update(active=any_active)

        demo.load(_refresh, outputs=[sources_state, poll_timer])
        refresh_btn.click(_refresh, outputs=[sources_state, poll_timer])
        poll_timer.tick(_refresh, outputs=[sources_state, poll_timer])

        def _on_view_change(v):
            return v

        view_mode.change(_on_view_change, inputs=view_mode, outputs=view_mode_state)

        def _on_upload(path):
            msg = _save_upload(path, media_dir)
            sources = _load_sources(media_dir, registry)
            any_active = any(s.get("active_job_id") for s in sources)
            return gr.update(value=msg, visible=True), sources, gr.update(active=any_active)

        upload.change(_on_upload, inputs=upload, outputs=[upload_msg, sources_state, poll_timer])

        # --- Drive ブラウズ（複数選択 → キュー投入） ---

        def _entries_to_choices(entries, sort_mode: str) -> list[tuple[str, str]]:
            """list[BrowseEntry] → (label, value) の CheckboxGroup choices。

            label: "[✓] path (size, date)" 表示用。value: 絶対パス。
            """
            from datetime import datetime
            # ソート
            if sort_mode == "size":
                entries = sorted(entries, key=lambda e: -e.size_bytes)
            elif sort_mode == "mtime":
                entries = sorted(entries, key=lambda e: -e.mtime)
            else:
                entries = sorted(entries, key=lambda e: e.rel.lower())
            out: list[tuple[str, str]] = []
            for e in entries:
                mb = e.size_bytes / (1024 * 1024)
                try:
                    dt = datetime.fromtimestamp(e.mtime).strftime("%Y-%m-%d %H:%M")
                except (OverflowError, ValueError):
                    dt = ""
                mark = "✓ " if e.already_imported else "○ "
                label = f"{mark}{e.rel}  ({mb:.1f} MB, {dt})"
                out.append((label, e.path))
            return out

        def _on_scan(path: str, sort_mode: str):
            if not path:
                return (
                    gr.update(choices=[], value=[]),
                    [],
                    gr.update(value="_パスを入力してください_", visible=True),
                )
            entries = list_videos_under(path, media_root=str(media_dir))
            if not entries:
                return (
                    gr.update(choices=[], value=[]),
                    [],
                    gr.update(value=f"`{path}` の下に動画が見つかりませんでした。", visible=True),
                )
            duplicate_count = sum(1 for e in entries if e.already_imported)
            msg = f"**{len(entries)}** 件見つかりました"
            if duplicate_count:
                msg += f"（うち **{duplicate_count}** 件は取込済 / 変換済 ✓）"
            return (
                gr.update(choices=_entries_to_choices(entries, sort_mode), value=[]),
                list(entries),
                gr.update(value=msg, visible=True),
            )

        scan_btn.click(
            _on_scan,
            inputs=[browse_path, sort_by],
            outputs=[file_picker, entries_state, browse_msg],
        )

        def _on_sort_change(entries, sort_mode):
            if not entries:
                return gr.update(choices=[], value=[])
            return gr.update(choices=_entries_to_choices(entries, sort_mode), value=[])

        sort_by.change(
            _on_sort_change,
            inputs=[entries_state, sort_by],
            outputs=file_picker,
        )

        def _on_select_all(entries, sort_mode):
            if not entries:
                return gr.update(value=[])
            choices = _entries_to_choices(entries, sort_mode)
            return gr.update(value=[v for _, v in choices])

        select_all_btn.click(
            _on_select_all, inputs=[entries_state, sort_by], outputs=file_picker,
        )
        clear_sel_btn.click(lambda: gr.update(value=[]), outputs=file_picker)

        def _on_queue(selected_paths: list[str]):
            """選択した複数ファイルを順番にステージ＋キュー投入。"""
            from pathlib import Path as _P
            if not selected_paths:
                return (
                    gr.update(value="⚠️ ファイルを選択してから押してください", visible=True),
                    _load_sources(media_dir, registry),
                    gr.update(active=False),
                )

            queued: list[str] = []
            skipped: list[str] = []
            failed: list[str] = []

            for src_path in selected_paths:
                src = _P(src_path)
                vid = resolve_video_id(src.name)

                # 既に変換済み or キュー内なら skip
                if registry.find_active_by_video_id(vid):
                    skipped.append(f"{src.name}（キュー内）")
                    continue
                if (media_dir / "hls" / vid / "master.m3u8").exists():
                    skipped.append(f"{src.name}（変換済）")
                    continue
                # ローカル staging（shutil.copy2 がここで走る。大ファイルだとブロックする点に注意）
                stage_res = stage_to_local(src_path, str(staging_dir()))
                if not stage_res["ok"]:
                    failed.append(f"{src.name}: {stage_res['message']}")
                    continue
                staged_path = stage_res["path"]
                try:
                    registry.submit(
                        runner=lambda reg, job_id, _sp=staged_path, _name=src.name, _vid=vid: run_conversion(
                            registry=reg, job_id=job_id,
                            media_root=str(media_dir),
                            source_file=_name, video_id=_vid,
                            source_path=_sp,
                            cleanup_source_after=True,
                        ),
                        video_id=vid,
                        source_file=src.name,
                    )
                    queued.append(src.name)
                except ValueError as e:
                    failed.append(f"{src.name}: {e}")

            parts: list[str] = []
            if queued:
                parts.append(f"✅ **{len(queued)}** 件キュー投入: {', '.join(queued[:5])}"
                             + (f" ... 他{len(queued) - 5}件" if len(queued) > 5 else ""))
            if skipped:
                parts.append(f"⏭ **{len(skipped)}** 件スキップ: {', '.join(skipped[:5])}"
                             + (f" ... 他{len(skipped) - 5}件" if len(skipped) > 5 else ""))
            if failed:
                parts.append(f"⚠️ **{len(failed)}** 件失敗: {'; '.join(failed[:3])}")

            msg = " / ".join(parts) if parts else "(何も起きませんでした)"
            sources = _load_sources(media_dir, registry)
            any_active = any(s.get("active_job_id") for s in sources)
            return (
                gr.update(value=msg, visible=True),
                sources,
                gr.update(active=any_active),
            )

        convert_btn.click(
            _on_queue,
            inputs=file_picker,
            outputs=[browse_msg, sources_state, poll_timer],
        )

    return demo


# ---------------------------------------------------------------------------
# List / Card renderers (called from @gr.render)
# ---------------------------------------------------------------------------

def _sort_sources(sources: list[dict], sort_cfg: dict) -> list[dict]:
    col = sort_cfg.get("column", "filename")
    direction = sort_cfg.get("direction", "asc")
    reverse = direction == "desc"
    key_map = {
        "filename": lambda s: s.get("filename", "").lower(),
        "size": lambda s: s.get("size_bytes", 0),
        "modified": lambda s: s.get("modified_at", ""),
        "status": lambda s: (0 if s.get("active_job_id") else (1 if s.get("converted") else 2)),
    }
    key = key_map.get(col, key_map["filename"])
    return sorted(sources, key=key, reverse=reverse)


# 列幅配分（ヘッダと行で一致させる）: filename / size / modified / status / action
_LIST_SCALES = (4, 1, 2, 2, 1)


def _sort_indicator(sort_cfg: dict, col: str) -> str:
    if sort_cfg.get("column") != col:
        return ""
    return "  ▲" if sort_cfg.get("direction") == "asc" else "  ▼"


def _toggle_sort(sort_cfg: dict, col: str) -> dict:
    """同じ列を再クリック → 方向反転、別列 → 昇順で切替。"""
    if sort_cfg.get("column") == col:
        new_dir = "desc" if sort_cfg.get("direction") == "asc" else "asc"
        return {"column": col, "direction": new_dir}
    return {"column": col, "direction": "asc"}


def _size_cell(s: dict) -> str:
    if s.get("source_deleted"):
        return "—"
    return _format_size(s.get("size_bytes", 0))


def _render_list(
    sources, registry, sources_state, playing_state, player_area, poll_timer,
    sort_cfg, sort_state,
):
    """列ヘッダをクリックでソート可能なリスト。"""

    with gr.Column():
        # ヘッダ行: 各列はクリック可能なボタン（操作列を除く）
        with gr.Row(equal_height=True):
            with gr.Column(scale=_LIST_SCALES[0], min_width=120):
                name_hdr = gr.Button(f"ファイル名{_sort_indicator(sort_cfg, 'filename')}",
                                     size="sm", variant="secondary")
            with gr.Column(scale=_LIST_SCALES[1], min_width=60):
                size_hdr = gr.Button(f"サイズ{_sort_indicator(sort_cfg, 'size')}",
                                     size="sm", variant="secondary")
            with gr.Column(scale=_LIST_SCALES[2], min_width=100):
                modified_hdr = gr.Button(f"更新日時{_sort_indicator(sort_cfg, 'modified')}",
                                         size="sm", variant="secondary")
            with gr.Column(scale=_LIST_SCALES[3], min_width=80):
                status_hdr = gr.Button(f"状態{_sort_indicator(sort_cfg, 'status')}",
                                       size="sm", variant="secondary")
            with gr.Column(scale=_LIST_SCALES[4], min_width=80):
                gr.Markdown("**操作**")

        name_hdr.click(lambda cfg: _toggle_sort(cfg, "filename"),
                       inputs=sort_state, outputs=sort_state)
        size_hdr.click(lambda cfg: _toggle_sort(cfg, "size"),
                       inputs=sort_state, outputs=sort_state)
        modified_hdr.click(lambda cfg: _toggle_sort(cfg, "modified"),
                           inputs=sort_state, outputs=sort_state)
        status_hdr.click(lambda cfg: _toggle_sort(cfg, "status"),
                         inputs=sort_state, outputs=sort_state)

        # データ行
        for s in sources:
            job = registry.find_active_by_video_id(s["video_id"])
            with gr.Row(equal_height=True):
                with gr.Column(scale=_LIST_SCALES[0], min_width=120):
                    gr.Markdown(f"`{s['filename']}`")
                with gr.Column(scale=_LIST_SCALES[1], min_width=60):
                    gr.Markdown(_size_cell(s))
                with gr.Column(scale=_LIST_SCALES[2], min_width=100):
                    gr.Markdown(s["modified_at"][:16].replace("T", " "))
                with gr.Column(scale=_LIST_SCALES[3], min_width=80):
                    gr.HTML(_status_badge(s, job))
                with gr.Column(scale=_LIST_SCALES[4], min_width=80):
                    _make_action_button(
                        s, job, registry, sources_state, playing_state,
                        player_area, poll_timer,
                    )


def _render_cards(sources, registry, sources_state, playing_state, player_area, poll_timer):
    cols = 3
    for i in range(0, len(sources), cols):
        batch = sources[i:i + cols]
        with gr.Row(equal_height=True):
            for s in batch:
                job = registry.find_active_by_video_id(s["video_id"])
                with gr.Column(scale=1, min_width=240):
                    gr.HTML(_thumb_html(s.get("sprite")))
                    gr.Markdown(f"**`{s['filename']}`**\n\n{_size_cell(s)} · {s['modified_at'][:10]}")
                    gr.HTML(_status_badge(s, job))
                    _make_action_button(s, job, registry, sources_state, playing_state, player_area, poll_timer)


def _make_action_button(source, job, registry, sources_state, playing_state, player_area, poll_timer):
    """変換ボタン / 再生ボタンを現在状態に応じて 1 個だけ作成。"""
    from hls_video.config import media_root as _media_root
    media_dir = _media_root()

    # 既にアクティブジョブがあるなら "処理中" （無効化）
    if job and job.state in {"pending", "running"}:
        gr.Button("処理中", interactive=False, size="sm")
        return

    # 変換済みなら再生ボタン + (ソースが残っていれば) MP4 削除ボタン
    if source.get("converted"):
        with gr.Row():
            play_btn = gr.Button("▶ 再生", variant="primary", size="sm", scale=2)
            if not source.get("source_deleted"):
                delete_btn = gr.Button(
                    "🗑", variant="secondary", size="sm", scale=1,
                    min_width=44,
                )
            else:
                delete_btn = None  # ソース既に削除済 → ボタン不要

        def _do_play(current_playing, vid=source["video_id"]):
            if current_playing == vid:
                return empty_html(), None
            return iframe_html(vid), vid

        play_btn.click(_do_play, inputs=playing_state, outputs=[player_area, playing_state])

        if delete_btn is not None:
            def _do_delete(filename=source["filename"]):
                delete_source_file(str(media_dir), filename)
                sources = _load_sources(media_dir, registry)
                any_active = any(s.get("active_job_id") for s in sources)
                return sources, gr.update(active=any_active)
            delete_btn.click(_do_delete, outputs=[sources_state, poll_timer])
        return

    # ランタイム再起動後の再開待ち (staging に残存) → 再開ボタン
    if source.get("pending_staging"):
        resume_btn = gr.Button("▶ 再開", variant="primary", size="sm")

        def _do_resume(
            filename=source["filename"],
            vid=source["video_id"],
            staged=source["staged_path"],
        ):
            if registry.find_active_by_video_id(vid) is None:
                try:
                    registry.submit(
                        runner=lambda reg, job_id, _sp=staged, _name=filename, _vid=vid:
                        run_conversion(
                            registry=reg, job_id=job_id,
                            media_root=str(media_dir),
                            source_file=_name, video_id=_vid,
                            source_path=_sp,
                            # cleanup_source_after は自動で True に解決される
                        ),
                        video_id=vid,
                        source_file=filename,
                    )
                except ValueError:
                    pass
            sources = _load_sources(media_dir, registry)
            any_active = any(s.get("active_job_id") for s in sources)
            return sources, gr.update(active=any_active)

        resume_btn.click(_do_resume, outputs=[sources_state, poll_timer])
        return

    # 未変換なら変換ボタン
    conv_btn = gr.Button("変換", variant="primary", size="sm")

    def _do_convert(filename=source["filename"], vid=source["video_id"]):
        if registry.find_active_by_video_id(vid) is None:
            try:
                registry.submit(
                    runner=lambda reg, job_id: run_conversion(
                        registry=reg, job_id=job_id,
                        media_root=str(media_dir),
                        source_file=filename, video_id=vid,
                    ),
                    video_id=vid,
                    source_file=filename,
                )
            except ValueError:
                pass
        sources = _load_sources(media_dir, registry)
        any_active = any(s.get("active_job_id") for s in sources)
        return sources, gr.update(active=any_active)

    conv_btn.click(_do_convert, outputs=[sources_state, poll_timer])
