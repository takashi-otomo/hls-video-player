"""jobRegistry.test.js からの移植 + 並列キュー検証の追加テスト。"""

import threading
import time

import pytest

from hls_video.job_registry import JobRegistry


class TestBasicRegistry:
    def test_create_assigns_unique_id_and_pending_state(self):
        reg = JobRegistry(max_workers=1)
        a = reg.create(video_id="a", source_file="a.mp4")
        b = reg.create(video_id="b", source_file="b.mp4")
        assert a.id != b.id
        assert a.state == "pending"
        assert a.video_id == "a"

    def test_get_returns_job_by_id(self):
        reg = JobRegistry(max_workers=1)
        j = reg.create(video_id="x", source_file="x.mp4")
        assert reg.get(j.id).id == j.id

    def test_update_transitions(self):
        reg = JobRegistry(max_workers=1)
        j = reg.create(video_id="x", source_file="x.mp4")
        reg.update(j.id, state="running")
        assert reg.get(j.id).state == "running"
        reg.update(j.id, state="completed")
        assert reg.get(j.id).state == "completed"

    def test_update_sets_started_and_finished_timestamps(self):
        reg = JobRegistry(max_workers=1)
        j = reg.create(video_id="x", source_file="x.mp4")
        reg.update(j.id, state="running")
        assert reg.get(j.id).started_at is not None
        reg.update(j.id, state="completed")
        assert reg.get(j.id).finished_at is not None

    def test_failed_with_error(self):
        reg = JobRegistry(max_workers=1)
        j = reg.create(video_id="x", source_file="x.mp4")
        reg.update(j.id, state="failed", error="boom")
        assert reg.get(j.id).state == "failed"
        assert reg.get(j.id).error == "boom"

    def test_find_active_by_video_id(self):
        reg = JobRegistry(max_workers=1)
        j = reg.create(video_id="x", source_file="x.mp4")
        assert reg.find_active_by_video_id("x").id == j.id
        reg.update(j.id, state="completed")
        assert reg.find_active_by_video_id("x") is None

    def test_list_newest_first(self):
        reg = JobRegistry(max_workers=1)
        a = reg.create(video_id="a", source_file="a.mp4")
        # Force monotonic timestamp diff
        time.sleep(0.001)
        b = reg.create(video_id="b", source_file="b.mp4")
        ids = [j.id for j in reg.list()]
        assert ids[0] == b.id and ids[1] == a.id


class TestParallelQueue:
    def test_submit_runs_in_worker_pool(self):
        reg = JobRegistry(max_workers=2)
        done = threading.Event()

        def runner(reg_, job_id):
            reg_.update(job_id, state="running")
            time.sleep(0.05)
            reg_.update(job_id, state="completed")
            done.set()

        job = reg.submit(runner=runner, video_id="a", source_file="a.mp4")
        done.wait(timeout=2)
        assert reg.get(job.id).state == "completed"

    def test_max_concurrent_respected(self):
        """max_workers=2 で 3 本投入すると running 2 本 + pending 1 本になる瞬間がある。"""
        reg = JobRegistry(max_workers=2)
        start_barrier = threading.Barrier(3)  # 2 workers + test thread
        release = threading.Event()

        def blocking_runner(reg_, job_id):
            reg_.update(job_id, state="running")
            start_barrier.wait()  # 2 workers gather here
            release.wait(timeout=3)
            reg_.update(job_id, state="completed")

        reg.submit(runner=blocking_runner, video_id="a", source_file="a.mp4")
        reg.submit(runner=blocking_runner, video_id="b", source_file="b.mp4")
        third = reg.submit(runner=blocking_runner, video_id="c", source_file="c.mp4")

        start_barrier.wait(timeout=3)  # 2 workers are now in flight
        # サードジョブはまだワーカー空き待ち → pending のまま
        assert reg.get(third.id).state == "pending"

        running = [j for j in reg.list() if j.state == "running"]
        assert len(running) == 2

        release.set()

    def test_second_submit_for_same_video_rejected(self):
        reg = JobRegistry(max_workers=1)

        def runner(reg_, job_id):
            reg_.update(job_id, state="running")
            time.sleep(0.1)
            reg_.update(job_id, state="completed")

        reg.submit(runner=runner, video_id="x", source_file="x.mp4")
        with pytest.raises(ValueError):
            reg.submit(runner=runner, video_id="x", source_file="x.mp4")
