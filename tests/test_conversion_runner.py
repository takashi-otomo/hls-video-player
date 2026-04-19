"""conversionRunner.js からの移植。

FFmpeg 本体は呼ばず、`hls_convert` / `sprite_generate` をモック化して
ステージ加重進捗の合算ロジックを検証する。
"""

import threading

import pytest

from hls_video.conversion_runner import STAGE_WEIGHTS, run_conversion
from hls_video.job_registry import JobRegistry


def test_stage_weights_sum_to_one():
    total = sum(STAGE_WEIGHTS.values())
    assert total == pytest.approx(1.0, abs=1e-9)


def test_run_conversion_updates_stages_and_progress(tmp_path, monkeypatch):
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="sample", source_file="sample.mp4")

    # ソースファイルを作って存在チェックを通す
    (tmp_path / "source").mkdir(parents=True)
    (tmp_path / "source" / "sample.mp4").write_bytes(b"fake")
    (tmp_path / "hls").mkdir()
    (tmp_path / "sprites").mkdir()

    captured_progress: list[float] = []

    def fake_probe(_path):
        return 100.0

    def fake_convert(**kwargs):
        # 0.5 のタイミングで on_progress を呼び、hls ステージ内 50% ≈ 全体 44.5%
        kwargs["on_progress"](0.5, {"current_time": 50})
        kwargs["on_progress"](1.0, {"current_time": 100})

    def fake_sprite(**kwargs):
        kwargs["on_progress"](0.5, {"current_time": 50})

    import hls_video.conversion_runner as runner_mod
    monkeypatch.setattr(runner_mod, "probe_duration_seconds", fake_probe)
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", fake_convert)
    monkeypatch.setattr(runner_mod, "generate_sprite", fake_sprite)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path), source_file="sample.mp4", video_id="sample",
    )

    final = reg.get(job.id)
    assert final.state == "completed"
    assert final.progress == pytest.approx(1.0)
    assert final.stage == "done"
    assert final.duration_seconds == 100.0


def test_run_conversion_marks_failed_on_exception(tmp_path, monkeypatch):
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="bad", source_file="bad.mp4")
    (tmp_path / "source").mkdir(parents=True)
    (tmp_path / "source" / "bad.mp4").write_bytes(b"fake")

    import hls_video.conversion_runner as runner_mod
    monkeypatch.setattr(runner_mod, "probe_duration_seconds", lambda _p: 10.0)

    def boom(**kwargs):
        raise RuntimeError("ffmpeg blew up")
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", boom)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path), source_file="bad.mp4", video_id="bad",
    )
    final = reg.get(job.id)
    assert final.state == "failed"
    assert "ffmpeg" in final.error


def test_run_conversion_fails_fast_when_source_missing(tmp_path):
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="nope", source_file="nope.mp4")
    (tmp_path / "source").mkdir(parents=True)
    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path), source_file="nope.mp4", video_id="nope",
    )
    final = reg.get(job.id)
    assert final.state == "failed"
    assert "not found" in final.error.lower()
