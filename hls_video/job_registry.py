"""変換ジョブ登録簿。ThreadPoolExecutor ベースの並列キュー。

Node 側 utils/jobRegistry.js より拡張:
- `max_workers` で同時実行数を制限
- 未着手 submit は `pending` → ワーカー空き次第 `running`
- 同一 video_id への再投入は `ValueError`
- すべてスレッドセーフ
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass
class Job:
    id: str
    video_id: str
    source_file: str
    state: str = "pending"   # pending | running | completed | failed
    stage: Optional[str] = None
    progress: float = 0.0
    stage_progress: float = 0.0
    error: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "video_id": self.video_id,
            "source_file": self.source_file,
            "state": self.state,
            "stage": self.stage,
            "progress": self.progress,
            "stage_progress": self.stage_progress,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobRegistry:
    def __init__(self, *, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hls-worker")
        self.max_workers = max_workers

    # --- Mutation ---

    def create(self, *, video_id: str, source_file: str) -> Job:
        job = Job(id=str(uuid.uuid4()), video_id=video_id, source_file=source_file)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def update(self, job_id: str, **patch) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for k, v in patch.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            # state transition 補助
            if patch.get("state") == "running" and job.started_at is None:
                job.started_at = datetime.now(tz=timezone.utc).isoformat()
            if patch.get("state") in {"completed", "failed"} and job.finished_at is None:
                job.finished_at = datetime.now(tz=timezone.utc).isoformat()
            return job

    # --- Query ---

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def find_active_by_video_id(self, video_id: str) -> Optional[Job]:
        with self._lock:
            for job in self._jobs.values():
                if job.video_id == video_id and job.state in {"pending", "running"}:
                    return job
            return None

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    # --- Execution ---

    def submit(
        self,
        *,
        runner: Callable[["JobRegistry", str], None],
        video_id: str,
        source_file: str,
    ) -> Job:
        """新規ジョブを登録して ThreadPoolExecutor に投入。既にアクティブなら ValueError。"""
        if self.find_active_by_video_id(video_id) is not None:
            raise ValueError(f"video_id {video_id!r} already has an active job")
        job = self.create(video_id=video_id, source_file=source_file)
        self._pool.submit(self._wrap_runner, runner, job.id)
        return job

    def _wrap_runner(self, runner: Callable[["JobRegistry", str], None], job_id: str) -> None:
        try:
            runner(self, job_id)
        except Exception as err:
            self.update(job_id, state="failed", error=str(err)[:500])

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
