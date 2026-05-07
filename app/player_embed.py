"""プレイヤー埋込用 HTML 生成 + ライブラリ閲覧 API。

Gradio の gr.HTML は script を実行しないため、FastAPI にプレイヤーページを
返すルートを追加し、Gradio 側は iframe で表示する。

データソースは hls_video.library_catalog（{LIBRARY_ROOT}/converted/ を走査）。
"""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from app.static_mount import _serve_library_file
from hls_video.favorites import (
    load_favorites, set_favorite, toggle_favorite,
)
from hls_video.library_catalog import get_video, list_videos
from hls_video.library_settings import (
    get_library_root, set_library_root, validate_library_root,
)

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
    height: 100dvh;
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

  .topbar {{
    display: none;
    align-items: center; gap: 0.5rem;
    padding: 0.5rem 0.75rem; background: #0a0c10;
    border-bottom: 1px solid #272c36;
    flex-shrink: 0;
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

  /* スマホ横置き */
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
    .topbar.show .title {{ display: none; }}
    .topbar.show a.back {{
      padding: 0.22rem 0.55rem; font-size: 0.78rem;
      background: rgba(26, 29, 36, 0.9);
    }}
    #mount {{ max-width: 100%; height: 100%; }}
    .wrap {{ padding: 0; }}
  }}

  @media (min-width: 900px) and (min-height: 600px) {{
    .wrap {{ padding: 1rem; }}
  }}

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
  if (window.top === window.self) {{
    document.getElementById('topbar').classList.add('show');
  }}
  window.HlsPlayer.init(document.getElementById("mount"), "{safe_id}");

  window.addEventListener('orientationchange', () => {{
    setTimeout(() => window.dispatchEvent(new Event('resize')), 150);
  }});
</script>
</body>
</html>"""


def iframe_html(video_id: str) -> str:
    safe_id = html.escape(video_id, quote=True)
    return (
        f'<iframe src="/player/{safe_id}" '
        f'style="width:100%;aspect-ratio:16/9;border:0;border-radius:6px;background:#000" '
        f'allow="fullscreen;autoplay" allowfullscreen></iframe>'
    )


def empty_html() -> str:
    return '<div style="min-height:0"></div>'


router = APIRouter()


@router.get("/player/{video_id}", response_class=HTMLResponse)
def _player_page(video_id: str):
    return HTMLResponse(player_page_html(video_id))


def _video_to_api(entry: dict) -> dict:
    """library_catalog のエントリを camelCase に整形して返す。"""
    return {
        "id": entry["id"],
        "title": entry["title"],
        "duration": entry.get("duration", 0.0),
        "width": entry.get("width", 0),
        "height": entry.get("height", 0),
        "container": entry.get("container", ""),
        "codec": entry.get("codec", ""),
        "formatLabel": entry.get("format_label", ""),
        "isFavorite": bool(entry.get("is_favorite", False)),
        "masterUrl": entry["master_url"],
        "posterUrl": entry["poster_url"],
        "thumbs": entry.get("thumbs", []),
    }


@router.get("/api/videos")
def _video_list():
    return JSONResponse([_video_to_api(v) for v in list_videos()])


@router.get("/api/videos/{video_id}")
def _video_meta(video_id: str):
    entry = get_video(video_id)
    if not entry:
        raise HTTPException(status_code=404, detail="not_found")
    return JSONResponse(_video_to_api(entry))


# ---------------------------------------------------------------------------
# /library/* — ライブラリ設定に従って動的にファイルを配信
# ---------------------------------------------------------------------------
@router.get("/library/{rel_path:path}")
def _library_file(rel_path: str) -> Response:
    return _serve_library_file(rel_path)


# ---------------------------------------------------------------------------
# /api/settings — GUI からライブラリパスを取得・更新
# ---------------------------------------------------------------------------
class LibraryRootIn(BaseModel):
    library_root: str


@router.get("/api/settings")
def _get_settings():
    lib = get_library_root()
    return JSONResponse({
        "library_root": str(lib),
        "exists": lib.is_dir(),
    })


@router.post("/api/settings/library_root")
def _set_library_root(body: LibraryRootIn):
    ok, msg = validate_library_root(body.library_root)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    saved = set_library_root(body.library_root)
    return JSONResponse({"library_root": str(saved), "message": msg})


# ---------------------------------------------------------------------------
# /api/favorites — お気に入り (永続: {LIBRARY_ROOT}/favorites.json)
# ---------------------------------------------------------------------------
class FavoriteIn(BaseModel):
    favorited: bool | None = None  # None なら toggle


@router.get("/api/favorites")
def _list_favorites():
    return JSONResponse({"favorites": sorted(load_favorites())})


@router.post("/api/favorites/{video_id}")
def _set_favorite(video_id: str, body: FavoriteIn | None = None):
    """お気に入り状態を更新。

    - body が `{"favorited": true|false}` ならその値で設定
    - body が空 / null ならトグル
    """
    if body is None or body.favorited is None:
        new_state = toggle_favorite(video_id)
    else:
        new_state = set_favorite(video_id, body.favorited)
    return JSONResponse({"id": video_id, "isFavorite": new_state})


# ---------------------------------------------------------------------------
# /play — スマホ向け再生専用ページ
# ---------------------------------------------------------------------------

_PLAY_PAGE_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HLS Library</title>
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
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.75rem;
    padding: 0.75rem;
  }
  #grid.view-grid .card {
    color: inherit; text-decoration: none;
    background: #1a1d24; border: 1px solid #272c36; border-radius: 6px;
    overflow: hidden; transition: transform 0.12s, border-color 0.12s;
    display: flex; flex-direction: column;
  }
  #grid.view-grid .card .thumb-wrap {
    position: relative;
    width: 100%; aspect-ratio: 16 / 9;
  }
  #grid.view-grid .card .thumb {
    width: 100%; height: 100%;
  }
  #grid.view-grid .card .body { padding: 0.5rem 0.6rem; }
  #grid.view-grid .card .title {
    font-size: 0.8rem; word-break: break-all;
    font-family: "SF Mono", Menlo, monospace;
    line-height: 1.3;
    max-height: 2.6em; overflow: hidden;
  }
  #grid.view-grid .card .meta {
    display: flex; gap: 0.4rem; flex-wrap: wrap;
    margin-top: 0.3rem; font-size: 0.7rem; color: #8b93a1;
  }

  /* --- List view --- */
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
  #grid.view-list .card .thumb-wrap {
    position: relative;
    width: 160px;
    aspect-ratio: 16 / 9;
    flex-shrink: 0;
    border-right: 1px solid #272c36;
  }
  #grid.view-list .card .thumb {
    width: 100%; height: 100%;
  }
  #grid.view-list .card .body {
    flex: 1;
    padding: 0.4rem 0.7rem;
    display: flex; flex-direction: column; justify-content: center;
    gap: 0.2rem;
    min-width: 0;
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
  #grid.view-list .card .meta {
    display: flex; gap: 0.5rem; flex-wrap: wrap;
    font-size: 0.7rem; color: #8b93a1;
  }

  /* 共通サムネ */
  .card .thumb {
    background: #0a0c10 center/cover no-repeat;
  }
  .card:active { transform: scale(0.99); }
  .card:hover { border-color: #4aa8ff; }

  /* メタ情報チップ */
  .meta .chip {
    background: #0e1117; border: 1px solid #272c36;
    padding: 1px 6px; border-radius: 999px;
    white-space: nowrap;
  }
  .meta .chip.duration { color: #b8c0cc; }
  .meta .chip.format   { color: #8b93a1; font-family: "SF Mono", Menlo, monospace; }

  /* お気に入りボタン (★ アイコン: 右上に重ねる) */
  .fav-btn {
    position: absolute; top: 6px; right: 6px;
    width: 30px; height: 30px;
    border: none; border-radius: 50%;
    background: rgba(0, 0, 0, 0.55); color: #c8c8c8;
    font-size: 16px; line-height: 30px; padding: 0;
    cursor: pointer; transition: transform 0.1s, background 0.15s, color 0.15s;
    z-index: 2;
  }
  .fav-btn:hover { background: rgba(0, 0, 0, 0.8); color: #fff; transform: scale(1.1); }
  .fav-btn.on { color: #ffc857; background: rgba(0, 0, 0, 0.7); }
  .fav-btn.on:hover { color: #ffd778; }

  /* ヘッダーの「お気に入りのみ」フィルタボタン */
  header button#btn-fav.active { background: #ffc857; color: #04121f; border-color: #ffc857; }

  #empty { padding: 2rem; text-align: center; color: #8b93a1; }
</style>
</head>
<body>
<header>
  <h1>📱 Library</h1>
  <div class="actions">
    <button id="btn-fav" type="button" title="お気に入りのみ表示">★</button>
    <button id="btn-list" type="button" title="リスト表示">≡</button>
    <button id="btn-grid" type="button" title="グリッド表示">▦</button>
    <button id="btn-refresh" type="button" title="再読込">↻</button>
  </div>
</header>
<div id="grid" class="view-grid"></div>
<p id="empty" hidden>変換済の動画がまだありません。CLI: <code>python -m hls_video.library_cli</code></p>
<script>
const STORAGE_KEY = 'hls-play.viewMode';
const FAV_KEY = 'hls-play.favOnly';
const grid = document.getElementById('grid');
const btnList = document.getElementById('btn-list');
const btnGrid = document.getElementById('btn-grid');
const btnFav = document.getElementById('btn-fav');
const btnRefresh = document.getElementById('btn-refresh');

let _videos = [];
let _favOnly = false;

function applyView(mode) {
  grid.className = mode === 'list' ? 'view-list' : 'view-grid';
  btnList.classList.toggle('active', mode === 'list');
  btnGrid.classList.toggle('active', mode === 'grid');
  try { localStorage.setItem(STORAGE_KEY, mode); } catch (_) {}
}

btnList.addEventListener('click', () => applyView('list'));
btnGrid.addEventListener('click', () => applyView('grid'));
btnRefresh.addEventListener('click', () => load());
btnFav.addEventListener('click', () => {
  _favOnly = !_favOnly;
  btnFav.classList.toggle('active', _favOnly);
  try { localStorage.setItem(FAV_KEY, _favOnly ? '1' : '0'); } catch (_) {}
  render();
});

function fmtDuration(s) {
  s = Math.max(0, Math.floor(Number(s) || 0));
  if (!s) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

async function toggleFav(videoId, btnEl, item) {
  // 楽観的更新 → サーバ確定で同期
  const next = !btnEl.classList.contains('on');
  btnEl.classList.toggle('on', next);
  btnEl.textContent = next ? '★' : '☆';
  try {
    const res = await fetch(`/api/favorites/${encodeURIComponent(videoId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ favorited: next }),
    });
    const data = await res.json();
    btnEl.classList.toggle('on', !!data.isFavorite);
    btnEl.textContent = data.isFavorite ? '★' : '☆';
    item.isFavorite = !!data.isFavorite;
    if (_favOnly && !item.isFavorite) render();
  } catch (e) {
    console.error('toggle favorite failed', e);
    // ロールバック
    btnEl.classList.toggle('on', !next);
    btnEl.textContent = !next ? '★' : '☆';
  }
}

// hover スライドショー: poster → 5/30/50/60/80 → poster をループ
// frames は [{percent, url}, ...] の配列。先頭に poster を加えてサイクル。
function attachHoverSlideshow(thumbEl, posterUrl, frames, intervalMs) {
  if (!frames || !frames.length) {
    thumbEl.style.backgroundImage = `url('${posterUrl}')`;
    return;
  }
  const sequence = [posterUrl, ...frames.map(f => f.url)];
  // プリロード
  sequence.forEach(u => { const img = new Image(); img.src = u; });

  let idx = 0;
  let timer = null;
  thumbEl.style.backgroundImage = `url('${sequence[0]}')`;

  function step() {
    idx = (idx + 1) % sequence.length;
    thumbEl.style.backgroundImage = `url('${sequence[idx]}')`;
  }
  function start() {
    if (timer) return;
    timer = setInterval(step, intervalMs);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    idx = 0;
    thumbEl.style.backgroundImage = `url('${sequence[0]}')`;
  }
  thumbEl.addEventListener('mouseenter', start);
  thumbEl.addEventListener('mouseleave', stop);
  thumbEl.addEventListener('touchstart', start, { passive: true });
  thumbEl.addEventListener('touchend', stop);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function render() {
  const empty = document.getElementById('empty');
  grid.innerHTML = '';
  const visible = _favOnly ? _videos.filter(v => v.isFavorite) : _videos;
  if (!visible.length) {
    empty.textContent = _favOnly
      ? 'お気に入りに追加された動画はまだありません。'
      : '変換済の動画がまだありません。CLI: python -m hls_video.library_cli';
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  for (const v of visible) {
    const a = document.createElement('a');
    a.className = 'card';
    a.href = `/player/${encodeURIComponent(v.id)}`;
    const fmt = v.formatLabel || (v.container ? v.container.toUpperCase() : '');
    a.innerHTML = `
      <div class="thumb-wrap">
        <div class="thumb"></div>
        <button type="button" class="fav-btn ${v.isFavorite ? 'on' : ''}" title="お気に入り">${v.isFavorite ? '★' : '☆'}</button>
      </div>
      <div class="body">
        <div class="title">${escapeHtml(v.title)}</div>
        <div class="meta">
          <span class="chip duration">⏱ ${fmtDuration(v.duration)}</span>
          ${fmt ? `<span class="chip format">${escapeHtml(fmt)}</span>` : ''}
        </div>
      </div>
    `;
    const thumbEl = a.querySelector('.thumb');
    attachHoverSlideshow(thumbEl, v.posterUrl, v.thumbs, 700);

    const favBtn = a.querySelector('.fav-btn');
    favBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleFav(v.id, favBtn, v);
    });

    grid.appendChild(a);
  }
}

async function load() {
  const res = await fetch('/api/videos');
  _videos = await res.json();
  render();
}

const saved = (() => { try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; } })();
applyView(saved === 'grid' ? 'grid' : 'list');
const savedFav = (() => { try { return localStorage.getItem(FAV_KEY) === '1'; } catch (_) { return false; } })();
if (savedFav) {
  _favOnly = true;
  btnFav.classList.add('active');
}
load();
</script>
</body>
</html>"""


@router.get("/play", response_class=HTMLResponse)
def _play_page():
    return HTMLResponse(_PLAY_PAGE_HTML)
