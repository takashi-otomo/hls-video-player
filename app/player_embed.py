"""プレイヤー埋込用 HTML 生成。

Gradio の gr.HTML は script を実行しないため、FastAPI にプレイヤーページを
返すルートを追加し、Gradio 側は iframe で表示する。
"""

from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from hls_video.config import media_root
from hls_video.video_catalog import list_videos

_VIDEOJS_VERSION = "8.21.1"


def player_page_html(video_id: str) -> str:
    safe_id = html.escape(video_id, quote=True)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_id}</title>
<link href="https://vjs.zencdn.net/{_VIDEOJS_VERSION}/video-js.css" rel="stylesheet">
<link href="/static/player.css" rel="stylesheet">
<style>
  html, body {{ margin: 0; padding: 0; background: #000; color: #fff; font-family: sans-serif; }}
  .wrap {{ max-width: 100%; }}
</style>
</head>
<body>
<div class="wrap"><div id="mount"></div></div>
<script src="https://vjs.zencdn.net/{_VIDEOJS_VERSION}/video.min.js"></script>
<script src="/static/playerFactory.js"></script>
<script>
  window.HlsPlayer.init(document.getElementById("mount"), "{safe_id}");
</script>
</body>
</html>"""


def iframe_html(video_id: str) -> str:
    """Gradio UI 側に挿入する iframe HTML。"""
    safe_id = html.escape(video_id, quote=True)
    return (
        f'<iframe src="/player/{safe_id}" '
        f'style="width:100%;aspect-ratio:16/9;border:0;border-radius:6px;background:#000" '
        f'allow="fullscreen;autoplay" allowfullscreen></iframe>'
    )


def empty_html() -> str:
    return '<div style="min-height:0"></div>'


# FastAPI に登録するルーター
router = APIRouter()


@router.get("/player/{video_id}", response_class=HTMLResponse)
def _player_page(video_id: str):
    return HTMLResponse(player_page_html(video_id))


# playerFactory.js が呼び出すメタ API。Node 実装と同じ形式で返す。
@router.get("/api/videos/{video_id}")
def _video_meta(video_id: str):
    videos = list_videos(str(media_root()))
    match = next((v for v in videos if v["id"] == video_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="not_found")
    sprite = match.get("sprite")
    # JS 側の camelCase 期待値に合わせてキーを整形
    if sprite:
        sprite = {
            "sheets": sprite["sheets"],
            "sheetCount": sprite["sheet_count"],
            "vttUrl": sprite.get("vtt_url"),
            "tileWidth": sprite.get("tile_width"),
            "tileHeight": sprite.get("tile_height"),
            "columns": sprite.get("columns"),
            "rows": sprite.get("rows"),
            "interval": sprite.get("interval"),
            "tileCount": sprite.get("tile_count"),
        }
    return JSONResponse({
        "id": match["id"],
        "title": match["title"],
        "masterUrl": match["master_url"],
        "sprite": sprite,
    })
