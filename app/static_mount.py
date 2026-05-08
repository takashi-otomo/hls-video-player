"""ライブラリ配下と同梱静的アセットの配信。

- `/library/...` は **動的解決**: 各リクエスト時に `library_settings` から
  ライブラリルートを取得し、`{lib_root}/{converted_dir}/...` から配信する。
  GUI でパスを変更すると即座に切り替わる（再起動不要）。
- `/static/...` はリポジトリ同梱（パスは固定）。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from hls_video.config import converted_dir_name
from hls_video.library_settings import get_library_root


_MIME_OVERRIDES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".vtt": "text/vtt",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
}


def _cache_headers(ext: str) -> dict[str, str]:
    h = {"Access-Control-Allow-Origin": "*"}
    if ext == ".ts":
        h["Cache-Control"] = "public, max-age=31536000, immutable"
    elif ext in (".jpg", ".jpeg", ".png"):
        h["Cache-Control"] = "public, max-age=86400"
    elif ext == ".m3u8":
        h["Cache-Control"] = "no-cache"
    return h


def _serve_library_file(rel_path: str) -> Response:
    """`/library/<rel>` をライブラリ設定に従って動的配信する。"""
    if ".." in rel_path.split("/"):
        raise HTTPException(status_code=400, detail="invalid path")
    lib = get_library_root()
    base = (lib / converted_dir_name()).absolute()
    target = (base / rel_path).absolute()
    # base 外への逸脱防止（symlink は許容するため resolve しない）
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="forbidden")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not_found")

    ext = target.suffix.lower()
    media_type = _MIME_OVERRIDES.get(ext)
    headers = _cache_headers(ext)
    return FileResponse(target, media_type=media_type, headers=headers)


# app パッケージ内に同梱した static ディレクトリ (pipx インストールでも一緒にコピーされる)
_PACKAGE_STATIC_DIR = Path(__file__).parent / "static"


def default_static_dir() -> Path:
    """同梱 static/ のパス (app パッケージ内)。pipx / pip いずれでも有効。"""
    return _PACKAGE_STATIC_DIR


def mount_static(app: FastAPI, *, static_dir: str | None = None) -> None:
    """`/static/*` を同梱 static/ にマウントする。

    static_dir 省略時は `app/static/` を自動使用 (pipx インストール時に
    パッケージと一緒にコピーされるため pyproject.toml 配下で確実に存在)。

    `/library/*` は player_embed.router 側で動的ルートとして登録するため、
    ここではマウントしない。
    """
    path = Path(static_dir) if static_dir else _PACKAGE_STATIC_DIR
    if not path.is_dir():
        raise RuntimeError(
            f"static directory not found: {path}\n"
            "pipx で再インストールしてください: pipx install --force \"<repo>[gui,app]\""
        )
    app.mount("/static", StaticFiles(directory=str(path)), name="static")


__all__ = ["mount_static", "default_static_dir", "_serve_library_file"]
