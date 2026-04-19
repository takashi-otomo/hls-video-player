import os

import pytest

from hls_video import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in [
        "MEDIA_ROOT",
        "FFMPEG_PATH",
        "FFPROBE_PATH",
        "FFMPEG_THREADS",
        "FFMPEG_PRESET",
        "FFMPEG_NICE",
        "MAX_CONCURRENT_JOBS",
    ]:
        monkeypatch.delenv(k, raising=False)


def test_defaults():
    assert config.ffmpeg_path() == "ffmpeg"
    assert config.ffprobe_path() == "ffprobe"
    assert config.ffmpeg_threads() == 2
    assert config.ffmpeg_preset() == "veryfast"
    assert config.ffmpeg_nice() is None
    assert config.max_concurrent_jobs() == 2


def test_ffmpeg_threads_env_override(monkeypatch):
    monkeypatch.setenv("FFMPEG_THREADS", "4")
    assert config.ffmpeg_threads() == 4


def test_ffmpeg_threads_floor_one(monkeypatch):
    monkeypatch.setenv("FFMPEG_THREADS", "0")
    assert config.ffmpeg_threads() == 1


def test_ffmpeg_nice_parses_int(monkeypatch):
    monkeypatch.setenv("FFMPEG_NICE", "10")
    assert config.ffmpeg_nice() == 10


def test_ffmpeg_nice_invalid_returns_none(monkeypatch):
    monkeypatch.setenv("FFMPEG_NICE", "abc")
    assert config.ffmpeg_nice() is None


def test_ffmpeg_nice_empty_returns_none(monkeypatch):
    monkeypatch.setenv("FFMPEG_NICE", "")
    assert config.ffmpeg_nice() is None


def test_max_concurrent_jobs_floor_one(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "0")
    assert config.max_concurrent_jobs() == 1


def test_media_root_expands(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    assert config.media_root() == tmp_path.resolve()
