"""Gradio が内部で持つ FastAPI app に、HLS / sprites / 静的アセットを
正しい MIME で配信するマウントを追加する。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


# 既定の StaticFiles は MIME を拡張子から推測するが、.m3u8 / .ts / .vtt は
# OS 依存で正しく引けないことがあるため、サブクラスで明示する。
class HlsStaticFiles(StaticFiles):
    _OVERRIDES = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".vtt": "text/vtt",
    }

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        ext = Path(path).suffix.lower()
        if ext in self._OVERRIDES:
            response.headers["Content-Type"] = self._OVERRIDES[ext]
            if ext == ".ts":
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif ext == ".m3u8":
                response.headers["Cache-Control"] = "no-cache"
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response


def mount_static(app: FastAPI, *, media_root: str, static_dir: str) -> None:
    media = Path(media_root)
    (media / "hls").mkdir(parents=True, exist_ok=True)
    (media / "sprites").mkdir(parents=True, exist_ok=True)
    (media / "source").mkdir(parents=True, exist_ok=True)

    app.mount("/hls", HlsStaticFiles(directory=str(media / "hls")), name="hls")
    app.mount("/sprites", HlsStaticFiles(directory=str(media / "sprites")), name="sprites")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
