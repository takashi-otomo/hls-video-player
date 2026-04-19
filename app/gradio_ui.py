"""Gradio Blocks UI。動画一覧（カード/リスト）、アップロード、変換、進捗、
再生（Video.js 埋込）を担う。Phase 2 のメインモジュール。"""

from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Generator

import gradio as gr

from hls_video.config import max_concurrent_jobs, media_root
from hls_video.conversion_runner import run_conversion
from hls_video.job_registry import Job, JobRegistry
from hls_video.source_catalog import list_sources, resolve_video_id, VIDEO_EXTS

from app.player_embed import empty_html, iframe_html


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
"""


# ---------------------------------------------------------------------------
# モデル関数（UI から呼ばれる純粋な関数群）
# ---------------------------------------------------------------------------

def _load_sources(media_dir: Path, registry: JobRegistry) -> list[dict]:
    sources = list_sources(str(media_dir))
    for s in sources:
        active = registry.find_active_by_video_id(s["video_id"])
        s["active_job_id"] = active.id if active else None
    return sources


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
        return f'<div>{bar}<div style="font-size:0.75rem;color:#8b93a1;margin-top:2px">{stage} <strong>{pct}%</strong></div></div>'
    if job and job.state == "failed":
        return f'<span style="color:#ff9595">✗ 失敗: {html.escape((job.error or "")[:80])}</span>'
    if source.get("converted"):
        return '<span style="color:#7fd498">✓ 変換済</span>'
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
        view_mode_state = gr.State("card")
        playing_state = gr.State(None)  # video_id | None

        with gr.Row():
            upload = gr.File(
                label="動画を追加（.mp4 / .mov / .mkv / .webm）",
                file_types=[f"*{ext}" for ext in VIDEO_EXTS],
                type="filepath",
                scale=3,
            )
            with gr.Column(scale=1, min_width=160):
                view_mode = gr.Radio(
                    choices=[("▦ カード", "card"), ("≡ リスト", "list")],
                    value="card",
                    label="表示",
                    container=False,
                )
                refresh_btn = gr.Button("↻ 更新", size="sm")
        upload_msg = gr.Markdown(visible=False)

        # プレイヤー領域
        player_area = gr.HTML(value=empty_html(), label="プレイヤー")

        # 進行中ジョブがあるときだけ 1.5 秒間隔で sources を再読込するポーリング Timer
        poll_timer = gr.Timer(1.5, active=False)

        # 動画一覧（動的再描画）
        @gr.render(inputs=[sources_state, view_mode_state])
        def draw_library(sources: list[dict], mode: str):
            if not sources:
                gr.Markdown("_media/source/ にファイルがありません。上からアップロードするか、既存ファイルを置いて「↻ 更新」を押してください。_")
                return

            if mode == "list":
                _render_list(sources, registry, sources_state, playing_state, player_area, poll_timer)
            else:
                _render_cards(sources, registry, sources_state, playing_state, player_area, poll_timer)

        # --- Events ---

        def _refresh():
            sources = _load_sources(media_dir, registry)
            any_active = any(s.get("active_job_id") for s in sources)
            # Timer はジョブ中だけアクティブ
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

    return demo


# ---------------------------------------------------------------------------
# List / Card renderers (called from @gr.render)
# ---------------------------------------------------------------------------

def _render_list(sources, registry, sources_state, playing_state, player_area, poll_timer):
    with gr.Column():
        gr.Markdown("| ファイル | サイズ | 更新 | 状態 | 操作 |\n|---|---|---|---|---|")
        for s in sources:
            job = registry.find_active_by_video_id(s["video_id"])
            with gr.Row(equal_height=True):
                gr.Markdown(f"`{s['filename']}`")
                gr.Markdown(_format_size(s["size_bytes"]))
                gr.Markdown(s["modified_at"][:16].replace("T", " "))
                gr.HTML(_status_badge(s, job))
                _make_action_button(s, job, registry, sources_state, playing_state, player_area, poll_timer)


def _render_cards(sources, registry, sources_state, playing_state, player_area, poll_timer):
    cols = 3
    for i in range(0, len(sources), cols):
        batch = sources[i:i + cols]
        with gr.Row(equal_height=True):
            for s in batch:
                job = registry.find_active_by_video_id(s["video_id"])
                with gr.Column(scale=1, min_width=240):
                    gr.HTML(_thumb_html(s.get("sprite")))
                    gr.Markdown(f"**`{s['filename']}`**\n\n{_format_size(s['size_bytes'])} · {s['modified_at'][:10]}")
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

    # 変換済みなら再生ボタン
    if source.get("converted"):
        play_btn = gr.Button("▶ 再生", variant="primary", size="sm")

        def _do_play(current_playing, vid=source["video_id"]):
            if current_playing == vid:
                return empty_html(), None
            return iframe_html(vid), vid

        play_btn.click(_do_play, inputs=playing_state, outputs=[player_area, playing_state])
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
