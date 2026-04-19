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
from hls_video.video_catalog import list_videos, resolve_sprite

_VIDEOJS_VERSION = "8.21.1"


def player_page_html(video_id: str) -> str:
    safe_id = html.escape(video_id, quote=True)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{safe_id}</title>
<link href="https://vjs.zencdn.net/{_VIDEOJS_VERSION}/video-js.css" rel="stylesheet">
<link href="/static/player.css" rel="stylesheet">
<style>
  html, body {{
    margin: 0; padding: 0; background: #000; color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    height: 100%;
    overflow: hidden;
  }}
  #root {{
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;        /* iOS Safari のバー高さ補正 */
  }}
  .wrap {{
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }}
  #mount {{
    width: 100%;
    max-width: 1280px;
  }}

  /* トップバー（直接アクセス / /play 経由の時だけ表示） */
  .topbar {{
    display: none;
    align-items: center; gap: 0.5rem;
    padding: 0.5rem 0.75rem; background: #0a0c10;
    border-bottom: 1px solid #272c36;
    flex-shrink: 0;
    /* iOS Safari のノッチ対応 */
    padding-top: calc(0.5rem + env(safe-area-inset-top));
    padding-left: calc(0.75rem + env(safe-area-inset-left));
    padding-right: calc(0.75rem + env(safe-area-inset-right));
  }}
  .topbar.show {{ display: flex; }}
  .topbar a.back {{
    color: #4aa8ff; text-decoration: none;
    font-size: 0.9rem; padding: 0.35rem 0.7rem;
    border: 1px solid #272c36; border-radius: 4px;
    background: #1a1d24;
    white-space: nowrap;
  }}
  .topbar a.back:hover {{ border-color: #4aa8ff; background: #22262f; }}
  .topbar .title {{
    color: #e6e8eb; flex: 1; font-size: 0.85rem;
    font-family: "SF Mono", Menlo, monospace;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}

  /* スマホ横置き: 画面いっぱいに動画を出すためにトップバーを半透明オーバーレイ化 */
  @media (orientation: landscape) and (max-height: 520px) {{
    .topbar.show {{
      position: fixed;
      top: 0; left: 0; right: auto;
      padding: 0.35rem 0.5rem;
      padding-top: calc(0.35rem + env(safe-area-inset-top));
      padding-left: calc(0.5rem + env(safe-area-inset-left));
      background: rgba(10, 12, 16, 0.55);
      border: none; border-bottom-right-radius: 8px;
      z-index: 10;
      transition: opacity 0.2s;
      opacity: 0.75;
    }}
    .topbar.show:hover {{ opacity: 1; }}
    .topbar.show .title {{ display: none; }}     /* 横置きは尺優先でタイトル非表示 */
    .topbar.show a.back {{
      padding: 0.22rem 0.55rem; font-size: 0.78rem;
      background: rgba(26, 29, 36, 0.9);
    }}
    #mount {{ max-width: 100%; height: 100%; }}  /* Video.js が 16:9 枠で最大化 */
    .wrap {{ padding: 0; }}
  }}

  /* 大画面では中央寄せ + 余白 */
  @media (min-width: 900px) and (min-height: 600px) {{
    .wrap {{ padding: 1rem; }}
  }}

  /* Video.js 側を container フィットに（aspectRatio:'16:9' と協調） */
  #mount .video-js {{ width: 100%; height: auto; max-height: 100%; }}
</style>
</head>
<body>
<div id="root">
  <div class="topbar" id="topbar">
    <a class="back" href="/play">← 一覧</a>
    <span class="title">{safe_id}</span>
  </div>
  <div class="wrap"><div id="mount"></div></div>
</div>
<script src="https://vjs.zencdn.net/{_VIDEOJS_VERSION}/video.min.js"></script>
<script src="/static/playerFactory.js"></script>
<script>
  // iframe 内（Gradio 動画一覧の埋込再生）ではトップバー非表示。
  if (window.top === window.self) {{
    document.getElementById('topbar').classList.add('show');
  }}
  window.HlsPlayer.init(document.getElementById("mount"), "{safe_id}");

  // モバイル横置きの変化でリサイズを促す（address bar の伸縮で 100dvh が変わる）
  window.addEventListener('orientationchange', () => {{
    setTimeout(() => window.dispatchEvent(new Event('resize')), 150);
  }});
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


def _video_to_api(entry: dict) -> dict:
    sprite = entry.get("sprite")
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
    return {
        "id": entry["id"],
        "title": entry["title"],
        "masterUrl": entry["master_url"],
        "sprite": sprite,
    }


# 変換済み動画の一覧（/play ページ等から呼ばれる）
@router.get("/api/videos")
def _video_list():
    videos = list_videos(str(media_root()))
    return JSONResponse([_video_to_api(v) for v in videos])


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


# ---------------------------------------------------------------------------
# /play — スマホ向け再生専用ページ（変換・アップロード関連 UI を一切含まない）
# ---------------------------------------------------------------------------

_PLAY_PAGE_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HLS Videos</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    background: #0a0c10; color: #e6e8eb;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  header {
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid #272c36;
    display: flex; justify-content: space-between; align-items: center;
    gap: 0.5rem;
  }
  header h1 { margin: 0; font-size: 1rem; font-weight: 600; flex: 1; }
  header .actions { display: flex; gap: 0.3rem; }
  header button {
    background: transparent; color: #8b93a1; border: 1px solid #272c36;
    padding: 0.3rem 0.55rem; border-radius: 4px; cursor: pointer;
    font-size: 0.8rem; font-family: inherit;
  }
  header button.active { background: #4aa8ff; color: #04121f; border-color: #4aa8ff; }
  header button:not(.active):hover { color: #e6e8eb; border-color: #4aa8ff; }

  /* --- Grid (card) view --- */
  #grid.view-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 0.75rem;
    padding: 0.75rem;
  }
  #grid.view-grid .card {
    display: block; color: inherit; text-decoration: none;
    background: #1a1d24; border: 1px solid #272c36; border-radius: 6px;
    overflow: hidden; transition: transform 0.12s, border-color 0.12s;
  }
  #grid.view-grid .card .thumb {
    width: 100%; aspect-ratio: 16 / 9;
  }
  #grid.view-grid .card .body { padding: 0.5rem 0.6rem; }
  #grid.view-grid .card .title {
    font-size: 0.8rem; word-break: break-all;
    font-family: "SF Mono", Menlo, monospace;
    line-height: 1.3;
    max-height: 2.6em; overflow: hidden;
  }

  /* --- List view (horizontal rows with thumbnail) --- */
  #grid.view-list {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.5rem;
  }
  #grid.view-list .card {
    display: flex;
    color: inherit; text-decoration: none;
    background: #1a1d24; border: 1px solid #272c36; border-radius: 6px;
    overflow: hidden; transition: border-color 0.12s;
    align-items: stretch;
  }
  #grid.view-list .card .thumb {
    width: 132px;                /* mobile-friendly; 132 * 9/16 ≈ 74px height */
    aspect-ratio: 16 / 9;
    flex-shrink: 0;
    border-right: 1px solid #272c36;
  }
  #grid.view-list .card .body {
    flex: 1;
    padding: 0.4rem 0.7rem;
    display: flex; align-items: center;
    min-width: 0;                /* prevent text overflow from pushing */
  }
  #grid.view-list .card .title {
    font-family: "SF Mono", Menlo, monospace;
    font-size: 0.82rem;
    line-height: 1.35;
    word-break: break-all;
    overflow: hidden; text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  /* 共通 */
  .card .thumb {
    background: #0a0c10 no-repeat 0 0;
    background-size: 1000% 1000%;
  }
  .card:active { transform: scale(0.99); }
  .card:hover { border-color: #4aa8ff; }

  #empty { padding: 2rem; text-align: center; color: #8b93a1; }
</style>
</head>
<body>
<header>
  <h1>📱 Videos</h1>
  <div class="actions">
    <button id="btn-list" type="button" title="リスト表示">≡</button>
    <button id="btn-grid" type="button" title="グリッド表示">▦</button>
    <button id="btn-refresh" type="button" title="再読込">↻</button>
  </div>
</header>
<div id="grid" class="view-grid"></div>
<p id="empty" hidden>変換済の動画がまだありません。</p>
<script>
const STORAGE_KEY = 'hls-play.viewMode';
const grid = document.getElementById('grid');
const btnList = document.getElementById('btn-list');
const btnGrid = document.getElementById('btn-grid');
const btnRefresh = document.getElementById('btn-refresh');

function applyView(mode) {
  grid.className = mode === 'list' ? 'view-list' : 'view-grid';
  btnList.classList.toggle('active', mode === 'list');
  btnGrid.classList.toggle('active', mode === 'grid');
  try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) {}
}

btnList.addEventListener('click', () => applyView('list'));
btnGrid.addEventListener('click', () => applyView('grid'));
btnRefresh.addEventListener('click', () => load());

async function load() {
  const empty = document.getElementById('empty');
  grid.innerHTML = '';
  empty.hidden = true;
  const res = await fetch('/api/videos');
  const videos = await res.json();
  if (!videos.length) { empty.hidden = false; return; }
  for (const v of videos) {
    const a = document.createElement('a');
    a.className = 'card';
    a.href = `/player/${encodeURIComponent(v.id)}`;
    const sheet = v.sprite?.sheets?.[0];
    const cols = v.sprite?.columns || 10;
    const rows = v.sprite?.rows || 10;
    const thumbStyle = sheet
      ? `background-image:url('${sheet}');background-size:${cols*100}% ${rows*100}%;background-position:0 0;`
      : '';
    a.innerHTML = `
      <div class="thumb" style="${thumbStyle}"></div>
      <div class="body"><div class="title">${v.title}</div></div>
    `;
    grid.appendChild(a);
  }
}

// 初期化: 保存済みモードを復元（既定はリスト — モバイル想定で縦スクロールが自然）
const saved = (() => { try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; } })();
applyView(saved === 'grid' ? 'grid' : 'list');
load();
</script>
</body>
</html>"""


@router.get("/play", response_class=HTMLResponse)
def _play_page():
    return HTMLResponse(_PLAY_PAGE_HTML)
