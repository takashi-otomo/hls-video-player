"""videoCatalog.test.js からの移植（multi-sheet ケース含む）。"""

import json
from pathlib import Path

from hls_video.video_catalog import list_videos, resolve_sprite


def _setup_media(tmp_path: Path):
    for sub in ("hls", "sprites"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)


def test_empty_when_no_hls_dir(tmp_path):
    assert list_videos(str(tmp_path)) == []


def test_returns_entries_with_master(tmp_path):
    _setup_media(tmp_path)
    video_dir = tmp_path / "hls" / "sample"
    video_dir.mkdir()
    (video_dir / "master.m3u8").write_text("#EXTM3U\n")

    videos = list_videos(str(tmp_path))
    assert len(videos) == 1
    assert videos[0]["id"] == "sample"
    assert "sample/master.m3u8" in videos[0]["master_url"]


def test_single_sheet_sprite(tmp_path):
    _setup_media(tmp_path)
    (tmp_path / "hls" / "demo").mkdir()
    (tmp_path / "hls" / "demo" / "master.m3u8").write_text("#EXTM3U")
    (tmp_path / "sprites" / "demo.jpg").write_bytes(b"jpg")
    (tmp_path / "sprites" / "demo.vtt").write_text("WEBVTT")
    (tmp_path / "sprites" / "demo.json").write_text(json.dumps({
        "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
        "interval": 10, "tileCount": 8, "sheetCount": 1,
    }))
    videos = list_videos(str(tmp_path))
    assert videos[0]["sprite"]["sheet_count"] == 1
    assert videos[0]["sprite"]["sheets"] == ["/sprites/demo.jpg"]
    assert videos[0]["sprite"]["rows"] == 10
    assert videos[0]["sprite"]["columns"] == 10
    assert videos[0]["sprite"]["vtt_url"] == "/sprites/demo.vtt"


def test_multi_sheet_sprite(tmp_path):
    _setup_media(tmp_path)
    (tmp_path / "hls" / "longvideo").mkdir()
    (tmp_path / "hls" / "longvideo" / "master.m3u8").write_text("#EXTM3U")
    for i in (1, 2, 3):
        (tmp_path / "sprites" / f"longvideo-{i}.jpg").write_bytes(b"x")
    (tmp_path / "sprites" / "longvideo.vtt").write_text("WEBVTT")
    (tmp_path / "sprites" / "longvideo.json").write_text(json.dumps({
        "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
        "interval": 10, "tileCount": 235, "sheetCount": 3,
    }))
    videos = list_videos(str(tmp_path))
    assert videos[0]["sprite"]["sheet_count"] == 3
    assert videos[0]["sprite"]["sheets"] == [
        "/sprites/longvideo-1.jpg",
        "/sprites/longvideo-2.jpg",
        "/sprites/longvideo-3.jpg",
    ]
    assert videos[0]["sprite"]["tile_count"] == 235


def test_resolve_sprite_returns_none_when_json_missing(tmp_path):
    (tmp_path / "sprites").mkdir()
    assert resolve_sprite(str(tmp_path / "sprites"), "nope") is None


def test_resolve_sprite_returns_none_when_all_sheets_missing(tmp_path):
    (tmp_path / "sprites").mkdir()
    (tmp_path / "sprites" / "x.json").write_text(json.dumps({
        "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
        "interval": 10, "tileCount": 5, "sheetCount": 1,
    }))
    # JSON はあるが jpg が無い
    assert resolve_sprite(str(tmp_path / "sprites"), "x") is None
