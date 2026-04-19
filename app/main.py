"""エントリポイント: `python -m app.main` で 7860 番ポートでアプリを起動する。

FastAPI に Gradio を `gr.mount_gradio_app` でマウントし、
/hls, /sprites, /static の静的ルートは FastAPI 側に先に登録する。
Uvicorn が 7860 ポートで待受。
"""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
import uvicorn
from fastapi import FastAPI

from app.gradio_ui import build_ui
from app.static_mount import mount_static
from app.player_embed import router as player_router
from hls_video.config import media_root


def build_app() -> FastAPI:
    media = media_root()
    static_dir = str(Path(__file__).parent.parent / "static")

    fastapi_app = FastAPI(title="hls-video-player")
    mount_static(fastapi_app, media_root=str(media), static_dir=static_dir)
    fastapi_app.include_router(player_router)

    demo = build_ui(media_dir=media)
    demo.queue()
    # Gradio を "/" 以下にマウント（先に登録した /hls, /sprites, /static, /player が優先）
    gr.mount_gradio_app(fastapi_app, demo, path="/")
    return fastapi_app


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(
        "app.main:build_app",
        host=host,
        port=port,
        factory=True,
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
