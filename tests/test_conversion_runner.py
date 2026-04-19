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
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda _p: (1920, 1080))
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
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda _p: (0, 0))

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


def test_run_conversion_uses_source_path_and_cleans_up(tmp_path, monkeypatch):
    """source_path 指定時: ffmpeg 入力にそれを使い、cleanup_source_after で削除。"""
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="staged", source_file="staged.mp4")

    # ステージングのローカルファイル（media_root/source/ ではない場所）
    staged = tmp_path / "stage" / "staged.mp4"
    staged.parent.mkdir()
    staged.write_bytes(b"STAGED")

    import hls_video.conversion_runner as runner_mod
    captured = {}

    def fake_probe(p):
        captured["probe_path"] = p
        return 10.0

    def fake_convert(**kw):
        captured["hls_input"] = kw.get("input_path")

    def fake_sprite(**kw):
        captured["sprite_input"] = kw.get("input_path")

    monkeypatch.setattr(runner_mod, "probe_duration_seconds", fake_probe)
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda _p: (0, 0))
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", fake_convert)
    monkeypatch.setattr(runner_mod, "generate_sprite", fake_sprite)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path),
        source_file="staged.mp4",
        video_id="staged",
        source_path=str(staged),
        cleanup_source_after=True,
    )

    assert reg.get(job.id).state == "completed"
    assert captured["probe_path"] == str(staged)
    assert captured["hls_input"] == str(staged)
    assert captured["sprite_input"] == str(staged)
    # ステージングファイルが消えていること
    assert not staged.exists()


def test_run_conversion_source_path_is_cleaned_up_by_default(tmp_path, monkeypatch):
    """`source_path` 指定時は既定でステージを削除（cleanup_source_after を省略）。"""
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="auto", source_file="auto.mp4")

    staged = tmp_path / "stage" / "auto.mp4"
    staged.parent.mkdir()
    staged.write_bytes(b"X")

    import hls_video.conversion_runner as runner_mod
    monkeypatch.setattr(runner_mod, "probe_duration_seconds", lambda p: 1.0)
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda p: (0, 0))
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", lambda **_k: None)
    monkeypatch.setattr(runner_mod, "generate_sprite", lambda **_k: None)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path),
        source_file="auto.mp4",
        video_id="auto",
        source_path=str(staged),
        # cleanup_source_after 未指定 → source_path があるので True に解決される
    )
    assert not staged.exists(), "source_path 指定時は既定で削除される"


def test_run_conversion_keeps_source_when_explicit_false(tmp_path, monkeypatch):
    """明示的に cleanup_source_after=False を渡せば保持する。"""
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="keep", source_file="keep.mp4")

    staged = tmp_path / "stage" / "keep.mp4"
    staged.parent.mkdir()
    staged.write_bytes(b"X")

    import hls_video.conversion_runner as runner_mod
    monkeypatch.setattr(runner_mod, "probe_duration_seconds", lambda p: 1.0)
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda p: (0, 0))
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", lambda **_k: None)
    monkeypatch.setattr(runner_mod, "generate_sprite", lambda **_k: None)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path),
        source_file="keep.mp4",
        video_id="keep",
        source_path=str(staged),
        cleanup_source_after=False,
    )
    assert staged.exists()


def test_run_conversion_without_source_path_does_not_touch_source(tmp_path, monkeypatch):
    """`source_path` を渡さなければ `media/source/` のファイルは絶対に消さない。"""
    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id="original", source_file="original.mp4")

    # media/source/original.mp4 を配置（ユーザー原本相当）
    (tmp_path / "source").mkdir()
    src_in_media = tmp_path / "source" / "original.mp4"
    src_in_media.write_bytes(b"USER_ORIGINAL")

    import hls_video.conversion_runner as runner_mod
    monkeypatch.setattr(runner_mod, "probe_duration_seconds", lambda p: 1.0)
    monkeypatch.setattr(runner_mod, "probe_video_dimensions", lambda p: (0, 0))
    monkeypatch.setattr(runner_mod, "convert_mp4_to_hls", lambda **_k: None)
    monkeypatch.setattr(runner_mod, "generate_sprite", lambda **_k: None)

    run_conversion(
        registry=reg, job_id=job.id,
        media_root=str(tmp_path),
        source_file="original.mp4",
        video_id="original",
        # source_path なし → cleanup は無効化されるべき
    )
    assert src_in_media.exists(), "原本は削除してはいけない"
    assert src_in_media.read_bytes() == b"USER_ORIGINAL"
