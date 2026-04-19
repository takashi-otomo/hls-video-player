"""Gradio + FastAPI 統合テスト。

実 FFmpeg は呼ばない。/hls /sprites /static の静的配信と
/api/videos/{id}, /player/{id} の動的ルートを検証。
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_with_fixtures(tmp_path, monkeypatch):
    """ダミーの media ツリーを作って FastAPI app を返す。"""
    media = tmp_path / "media"
    (media / "source").mkdir(parents=True)
    (media / "hls" / "vid1").mkdir(parents=True)
    (media / "sprites").mkdir(parents=True)

    (media / "source" / "vid1.mp4").write_bytes(b"fake")
    (media / "hls" / "vid1" / "master.m3u8").write_text("#EXTM3U\n")
    (media / "hls" / "vid1" / "720p_000.ts").write_bytes(b"\x47" * 188)  # fake TS packet
    (media / "sprites" / "vid1.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (media / "sprites" / "vid1.vtt").write_text("WEBVTT\n")
    (media / "sprites" / "vid1.json").write_text(json.dumps({
        "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
        "interval": 10, "tileCount": 3, "sheetCount": 1,
    }))

    monkeypatch.setenv("MEDIA_ROOT", str(media))
    # クリーンな import
    import importlib
    import app.main
    importlib.reload(app.main)
    return app.main.build_app()


def test_static_hls_m3u8_mime(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/hls/vid1/master.m3u8")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert r.text.startswith("#EXTM3U")


def test_static_ts_mime_and_cache(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/hls/vid1/720p_000.ts")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp2t"
    assert "immutable" in r.headers.get("cache-control", "")


def test_static_sprite_vtt_mime(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/sprites/vid1.vtt")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/vtt"


def test_static_sprite_jpg(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/sprites/vid1.jpg")
    assert r.status_code == 200
    # StaticFiles の既定は image/jpeg
    assert r.headers["content-type"].startswith("image/")


def test_api_videos_returns_sprite_metadata(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/api/videos/vid1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "vid1"
    assert body["masterUrl"] == "/hls/vid1/master.m3u8"
    assert body["sprite"]["sheets"] == ["/sprites/vid1.jpg"]
    assert body["sprite"]["columns"] == 10
    assert body["sprite"]["rows"] == 10


def test_api_videos_404(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/api/videos/nope")
    assert r.status_code == 404


def test_player_page_returns_html(app_with_fixtures):
    client = TestClient(app_with_fixtures)
    r = client.get("/player/vid1")
    assert r.status_code == 200
    assert "video-js" in r.text.lower() or "videojs" in r.text.lower()
    assert "vid1" in r.text
