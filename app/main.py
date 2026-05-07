"""エントリポイント: `python -m app.main` で 7860 番ポートでアプリを起動する。

新アーキテクチャ:
- ライブラリパスは GUI から指定可能（`hls_video.library_settings` で永続化）
- `/library/*` は static_mount 側で動的にライブラリパスを解決して配信
- Gradio は閲覧専用 UI (`gradio_library_ui`)
- 変換は CLI (`python -m hls_video.library_cli`) で行う
"""

from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
import uvicorn
from fastapi import FastAPI

from app.gradio_library_ui import build_ui
from app.player_embed import router as player_router
from app.static_mount import mount_static
from hls_video.logging_setup import setup_logging


def build_app() -> FastAPI:
    setup_logging()
    static_dir = str(Path(__file__).parent.parent / "static")

    fastapi_app = FastAPI(title="hls-video-player")
    mount_static(fastapi_app, static_dir=static_dir)
    fastapi_app.include_router(player_router)

    demo = build_ui()
    demo.queue()
    gr.mount_gradio_app(fastapi_app, demo, path="/")
    return fastapi_app


def main() -> None:
    setup_logging()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "7860"))
    uvicorn.run(
        "app.main:build_app",
        host=host,
        port=port,
        factory=True,
        log_level=os.environ.get("UVICORN_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
