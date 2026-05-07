"""GUI から指定したライブラリフォルダを永続化する設定ストア。

- 既定の保存先は `~/.config/hls-video-player/settings.json`
  （`HLS_SETTINGS_FILE` 環境変数で上書き可）
- 解決優先度（高→低）:
    1. 明示引数 (override)
    2. settings.json の "library_root"
    3. 環境変数 LIBRARY_ROOT
    4. カレントの ./library
- 保存値は絶対パス。シンボリックリンクは展開しない（Colab で
  /content/hls-video-player/library → Drive の symlink を維持するため）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from hls_video.config import library_root

logger = logging.getLogger(__name__)


_DEFAULT_SETTINGS_PATH = Path(
    os.environ.get(
        "HLS_SETTINGS_FILE",
        str(Path.home() / ".config" / "hls-video-player" / "settings.json"),
    )
).expanduser()


_LOCK = threading.RLock()


def _settings_path() -> Path:
    return _DEFAULT_SETTINGS_PATH


def _read_file() -> dict:
    p = _settings_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to read settings %s: %s", p, exc)
        return {}


def _write_file(data: dict) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(p)


def get_library_root(override: Optional[str | Path] = None) -> Path:
    """設定済みのライブラリルートを返す。

    override > settings.json > LIBRARY_ROOT env > ./library の順で解決。
    返り値は絶対パス（symlink は維持）。
    """
    if override:
        return Path(override).expanduser().absolute()

    with _LOCK:
        data = _read_file()
    saved = data.get("library_root")
    if saved:
        return Path(saved).expanduser().absolute()
    return library_root()


def set_library_root(value: str | Path) -> Path:
    """ライブラリルートを永続化して返す。

    存在しないパスでも保存はする（後でフォルダを作る運用を許容するため）が、
    呼び出し側は `validate_library_root` で事前チェック推奨。
    """
    path = Path(value).expanduser().absolute()
    with _LOCK:
        data = _read_file()
        data["library_root"] = str(path)
        _write_file(data)
    logger.info("library_root saved: %s", path)
    return path


def validate_library_root(value: str | Path) -> tuple[bool, str]:
    """指定パスが使えるかを判定し、(ok, message) を返す。"""
    if not value:
        return False, "パスが空です"
    p = Path(value).expanduser().absolute()
    if not p.exists():
        return False, f"パスが存在しません: {p}"
    if not p.is_dir():
        return False, f"ディレクトリではありません: {p}"
    return True, f"OK: {p}"
