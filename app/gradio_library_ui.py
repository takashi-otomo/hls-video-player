"""ライブラリ閲覧専用の Gradio UI。

- データソース: hls_video.library_catalog（{LIBRARY_ROOT}/converted/）
- アップロード / 変換キュー UI は持たない（変換は CLI: `python -m hls_video.library_cli`）
- カード/リスト両表示、サムネはホバーで poster→5/30/50/60/80→poster のスライドショー
- カードクリックで iframe プレイヤーを開く
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Optional

import gradio as gr

from hls_video.config import library_root
from hls_video.favorites import set_favorite
from hls_video.library_catalog import list_videos
from hls_video.library_settings import (
    get_library_root, set_library_root, validate_library_root,
)
from hls_video.logging_setup import setup_logging

from app.player_embed import empty_html, iframe_html

_logger = logging.getLogger(__name__)


_CSS = """
.hls-card-thumb-wrap {
  position: relative;
  width: 100%;
  padding-top: 56.25%; /* 16:9 */
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
  background-position: center center;
  background-repeat: no-repeat;
  background-size: cover;
  transition: transform 0.2s;
}
.hls-card-thumb-wrap:hover .hls-card-thumb { transform: scale(1.03); }
"""


def _slideshow_html(entry: dict) -> str:
    """1 枚のサムネ要素 HTML（hover で slideshow / 下記スクリプトで配線）。

    属性に poster URL と thumbs JSON を埋め、グローバル JS が初期化する。
    """
    poster = entry.get("poster_url") or ""
    frames = entry.get("thumbs") or []
    # data-frames は JSON 文字列。" を &quot; にしておけば属性値として安全に埋まる。
    import json as _json
    frames_attr = html.escape(_json.dumps(frames), quote=True)
    poster_attr = html.escape(poster, quote=True)
    style = (
        f"background-image:url('{poster_attr}');"
    )
    return (
        '<div class="hls-card-thumb-wrap">'
        f'<div class="hls-card-thumb hls-thumb-slideshow" '
        f'data-poster="{poster_attr}" data-frames="{frames_attr}" '
        f'style="{style}"></div>'
        '</div>'
    )


_SLIDESHOW_JS = """
<script>
(function () {
  // hover で poster → 5/30/50/60/80 → poster をループするスライドショー。
  // Gradio の再描画でノードが入れ替わるので、MutationObserver で再配線する。
  const INTERVAL_MS = 700;

  function attach(el) {
    if (el.__slideshowAttached) return;
    el.__slideshowAttached = true;
    const poster = el.dataset.poster || '';
    let frames = [];
    try { frames = JSON.parse(el.dataset.frames || '[]'); } catch (_) {}
    if (!frames.length) return;
    const seq = [poster].concat(frames.map(f => f.url));
    seq.forEach(u => { if (u) { const img = new Image(); img.src = u; } });

    let timer = null;
    let idx = 0;
    function step() {
      idx = (idx + 1) % seq.length;
      el.style.backgroundImage = `url('${seq[idx]}')`;
    }
    function start() {
      if (timer) return;
      timer = setInterval(step, INTERVAL_MS);
    }
    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      idx = 0;
      el.style.backgroundImage = `url('${seq[0]}')`;
    }
    el.addEventListener('mouseenter', start);
    el.addEventListener('mouseleave', stop);
    el.addEventListener('touchstart', start, { passive: true });
    el.addEventListener('touchend', stop);
  }

  function scan(root) {
    (root || document).querySelectorAll('.hls-thumb-slideshow').forEach(attach);
  }

  scan();
  const obs = new MutationObserver((muts) => {
    for (const m of muts) {
      m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.classList && n.classList.contains('hls-thumb-slideshow')) attach(n);
        scan(n);
      });
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
})();
</script>
"""


def _format_duration(s: float) -> str:
    s = int(s or 0)
    if s <= 0:
        return "—"
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _open_player(vid: str):
    """play_btn 共通の出力。playing_state / player_area / player_row(=close_btn) を更新。"""
    return (
        vid,
        gr.update(value=iframe_html(vid), visible=True),
        gr.update(visible=True),
    )


def _fav_button_label(is_fav: bool) -> str:
    return "★ 解除" if is_fav else "☆ 追加"


def _on_fav_click(vid: str, current_is_fav: bool, entries: list[dict]):
    """お気に入りトグル → ボタンラベルと entries_state を更新。"""
    new_state = not current_is_fav
    set_favorite(vid, new_state)
    # entries 内の該当行を書き換え
    updated = [
        {**e, "is_favorite": new_state} if e["id"] == vid else e
        for e in (entries or [])
    ]
    return (
        gr.update(value=_fav_button_label(new_state)),
        new_state,
        updated,
    )


def _render_list(entries: list[dict], playing_state, player_area, player_row, entries_state):
    """リスト表示（横長行 + 左にサムネ）。"""
    if not entries:
        gr.Markdown("_変換済の動画がまだありません。CLI: `python -m hls_video.library_cli`_")
        return

    # ヘッダ
    with gr.Row(equal_height=True):
        with gr.Column(scale=1, min_width=160):
            gr.Markdown("**サムネ**")
        with gr.Column(scale=3, min_width=160):
            gr.Markdown("**ファイル名**")
        with gr.Column(scale=1, min_width=70):
            gr.Markdown("**長さ**")
        with gr.Column(scale=1, min_width=90):
            gr.Markdown("**形式**")
        with gr.Column(scale=1, min_width=180):
            gr.Markdown("**操作**")

    for v in entries:
        with gr.Row(equal_height=True):
            with gr.Column(scale=1, min_width=160):
                gr.HTML(_slideshow_html(v))
            with gr.Column(scale=3, min_width=160):
                gr.HTML(
                    f'<div style="font-family:SF Mono,Menlo,monospace;font-size:0.85rem;'
                    f'word-break:break-all">{html.escape(v["title"])}</div>'
                )
            with gr.Column(scale=1, min_width=70):
                gr.HTML(
                    f'<span style="color:#8b93a1">{_format_duration(v.get("duration", 0))}</span>'
                )
            with gr.Column(scale=1, min_width=90):
                fmt = html.escape(v.get("format_label") or (v.get("container") or "").upper() or "—")
                gr.HTML(
                    f'<span style="color:#8b93a1;font-family:SF Mono,Menlo,monospace;'
                    f'font-size:0.78rem">{fmt}</span>'
                )
            with gr.Column(scale=1, min_width=180):
                with gr.Row():
                    play_btn = gr.Button("▶ 再生", size="sm", variant="primary", scale=1)
                    is_fav = bool(v.get("is_favorite"))
                    fav_state = gr.State(is_fav)
                    fav_btn = gr.Button(_fav_button_label(is_fav), size="sm", scale=1)
                vid = v["id"]
                play_btn.click(
                    lambda _vid=vid: _open_player(_vid),
                    outputs=[playing_state, player_area, player_row],
                )
                fav_btn.click(
                    lambda cur, ents, _vid=vid: _on_fav_click(_vid, cur, ents),
                    inputs=[fav_state, entries_state],
                    outputs=[fav_btn, fav_state, entries_state],
                )


def _render_cards(entries: list[dict], playing_state, player_area, player_row, entries_state):
    """カード表示（grid）。"""
    if not entries:
        gr.Markdown("_変換済の動画がまだありません。CLI: `python -m hls_video.library_cli`_")
        return

    cols = 4
    for row_start in range(0, len(entries), cols):
        with gr.Row():
            for v in entries[row_start:row_start + cols]:
                with gr.Column(min_width=180):
                    gr.HTML(_slideshow_html(v))
                    fmt = html.escape(v.get("format_label") or (v.get("container") or "").upper() or "")
                    fmt_html = (
                        f'<span style="display:inline-block;background:#0e1117;border:1px solid #272c36;'
                        f'border-radius:999px;padding:1px 6px;font-size:0.65rem;color:#8b93a1;'
                        f'font-family:SF Mono,Menlo,monospace;margin-left:4px">{fmt}</span>'
                        if fmt else ""
                    )
                    gr.HTML(
                        f'<div style="font-family:SF Mono,Menlo,monospace;font-size:0.78rem;'
                        f'word-break:break-all;line-height:1.3;margin-top:4px;'
                        f'max-height:2.6em;overflow:hidden">'
                        f'{html.escape(v["title"])}</div>'
                        f'<div style="font-size:0.7rem;color:#8b93a1;margin-top:2px">'
                        f'⏱ {_format_duration(v.get("duration", 0))}{fmt_html}</div>'
                    )
                    with gr.Row():
                        play_btn = gr.Button("▶ 再生", size="sm", scale=1)
                        is_fav = bool(v.get("is_favorite"))
                        fav_state = gr.State(is_fav)
                        fav_btn = gr.Button(_fav_button_label(is_fav), size="sm", scale=1)
                    vid = v["id"]
                    play_btn.click(
                        lambda _vid=vid: _open_player(_vid),
                        outputs=[playing_state, player_area, player_row],
                    )
                    fav_btn.click(
                        lambda cur, ents, _vid=vid: _on_fav_click(_vid, cur, ents),
                        inputs=[fav_state, entries_state],
                        outputs=[fav_btn, fav_state, entries_state],
                    )


def build_ui(*, lib_root: Optional[Path] = None) -> gr.Blocks:
    setup_logging()

    # 起動時に override 引数があれば永続保存しておく（環境変数で初期化されたケース等）
    if lib_root:
        set_library_root(lib_root)

    with gr.Blocks(title="HLS Video Library") as demo:
        gr.HTML(f"<style>{_CSS}</style>")
        gr.HTML(_SLIDESHOW_JS)
        gr.Markdown(
            "## HLS Video Library\n"
            "下の入力欄でライブラリフォルダを指定してください。"
            "変換は CLI: `python -m hls_video.library_cli` を実行してください。"
        )

        entries_state = gr.State([])
        view_mode_state = gr.State("list")
        playing_state = gr.State(None)

        # --- ライブラリパス設定セクション ---
        with gr.Group():
            gr.Markdown("### ライブラリフォルダ")
            with gr.Row():
                lib_path_input = gr.Textbox(
                    value=str(get_library_root()),
                    label="ライブラリのパス",
                    info="動画ファイルを置いてあるフォルダ。変更すると即座に一覧が切り替わります。",
                    scale=4,
                )
                save_btn = gr.Button("保存して反映", scale=1, variant="primary")
            lib_msg = gr.Markdown(visible=False)

        with gr.Row():
            gr.Markdown("### 動画一覧")
            with gr.Column(scale=0, min_width=320):
                with gr.Row():
                    view_mode = gr.Radio(
                        choices=[("≡ リスト", "list"), ("▦ カード", "card")],
                        value="list",
                        show_label=False,
                        container=False,
                        scale=2,
                    )
                    refresh_btn = gr.Button("↻ 更新", size="sm", scale=1)

        # プレイヤー領域 (再生ボタンを押すまでは折りたたまれている)
        with gr.Row(visible=False) as player_row:
            with gr.Column(scale=4):
                gr.Markdown("**▶ 再生中**")
            with gr.Column(scale=1, min_width=120):
                close_btn = gr.Button(
                    "✕ プレイヤーを閉じる", size="sm", variant="secondary",
                )
        player_area = gr.HTML(value=empty_html(), visible=False)

        @gr.render(inputs=[entries_state, view_mode_state])
        def _draw(entries: list[dict], mode: str):
            if mode == "list":
                _render_list(entries, playing_state, player_area, player_row, entries_state)
            else:
                _render_cards(entries, playing_state, player_area, player_row, entries_state)

        def _refresh():
            # 設定済みパスから動的に読む（GUI で変更された値を即反映）
            entries = list_videos()
            _logger.info(
                "library refresh: %d videos from %s",
                len(entries), get_library_root(),
            )
            return entries

        def _on_view(v):
            return v

        def _on_save_path(path: str):
            ok, msg = validate_library_root(path)
            if not ok:
                return (
                    gr.update(value=f"⚠️ {msg}", visible=True),
                    gr.update(),  # entries_state は触らない
                    gr.update(value=path),
                )
            saved = set_library_root(path)
            _logger.info("library_root updated via UI: %s", saved)
            entries = list_videos()
            return (
                gr.update(
                    value=f"✅ 保存しました: `{saved}` ({len(entries)} 件の動画を検出)",
                    visible=True,
                ),
                entries,
                gr.update(value=str(saved)),
            )

        def _close_player():
            """プレイヤーを折りたたみ、iframe を破棄して再生を停止する。"""
            return (
                None,                                    # playing_state
                gr.update(value=empty_html(), visible=False),  # player_area
                gr.update(visible=False),                # player_row (close_btn 含む)
            )

        demo.load(_refresh, outputs=entries_state)
        refresh_btn.click(_refresh, outputs=entries_state)
        view_mode.change(_on_view, inputs=view_mode, outputs=view_mode_state)
        save_btn.click(
            _on_save_path,
            inputs=lib_path_input,
            outputs=[lib_msg, entries_state, lib_path_input],
        )
        # Enter キーでも保存できるように
        lib_path_input.submit(
            _on_save_path,
            inputs=lib_path_input,
            outputs=[lib_msg, entries_state, lib_path_input],
        )
        close_btn.click(
            _close_player,
            outputs=[playing_state, player_area, player_row],
        )

    return demo
