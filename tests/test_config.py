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
        "FFMPEG_NVENC_PRESET",
        "FFMPEG_HWACCEL",
        "FFMPEG_VARIANTS",
        "FFMPEG_NICE",
        "MAX_CONCURRENT_JOBS",
    ]:
        monkeypatch.delenv(k, raising=False)


def test_defaults():
    assert config.ffmpeg_path() == "ffmpeg"
    assert config.ffprobe_path() == "ffprobe"
    # auto (0) が既定
    assert config.ffmpeg_threads() == 0
    # CPU encode は速度優先で ultrafast が既定
    assert config.ffmpeg_preset() == "ultrafast"
    # NVENC は p4 がバランス
    assert config.ffmpeg_nvenc_preset() == "p4"
    # HW accel は auto 検出
    assert config.ffmpeg_hwaccel() == "auto"
    # variants 絞り込みは未指定なら None
    assert config.ffmpeg_variants_filter() is None
    assert config.ffmpeg_nice() is None
    assert config.max_concurrent_jobs() == 2


def test_ffmpeg_threads_env_override(monkeypatch):
    monkeypatch.setenv("FFMPEG_THREADS", "4")
    assert config.ffmpeg_threads() == 4


def test_ffmpeg_threads_auto_explicit(monkeypatch):
    """0 は auto の意味。1 にクリップせずそのまま。"""
    monkeypatch.setenv("FFMPEG_THREADS", "0")
    assert config.ffmpeg_threads() == 0


def test_ffmpeg_threads_negative_clamped_to_zero(monkeypatch):
    monkeypatch.setenv("FFMPEG_THREADS", "-1")
    assert config.ffmpeg_threads() == 0


def test_ffmpeg_threads_invalid_returns_zero(monkeypatch):
    monkeypatch.setenv("FFMPEG_THREADS", "garbage")
    assert config.ffmpeg_threads() == 0


def test_ffmpeg_hwaccel_case_insensitive(monkeypatch):
    monkeypatch.setenv("FFMPEG_HWACCEL", "NVENC")
    assert config.ffmpeg_hwaccel() == "nvenc"


def test_ffmpeg_variants_filter_splits_csv(monkeypatch):
    monkeypatch.setenv("FFMPEG_VARIANTS", " 720p , 360p ")
    assert config.ffmpeg_variants_filter() == ["720p", "360p"]


def test_ffmpeg_variants_filter_empty_returns_none(monkeypatch):
    monkeypatch.setenv("FFMPEG_VARIANTS", "   ")
    assert config.ffmpeg_variants_filter() is None


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
