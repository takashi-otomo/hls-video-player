#!/usr/bin/env python3
"""converter コンテナの entry point。

`<LIBRARY_ROOT>/.jobs/` を polling し、未処理 job spec を見つけたら type に
応じて hls-convert / ts-merge を実行する。ログは <id>.log に追記、進捗は
<id>.status.json に書く。gui コンテナはこれらを WebSocket で配信する。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_ROOT = Path(os.environ.get("LIBRARY_ROOT", "/library"))
JOBS_DIR = LIBRARY_ROOT / ".jobs"
POLL_INTERVAL = 1.0
CLEANUP_AGE_HOURS = 24


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def find_pending_jobs() -> list[Path]:
    if not JOBS_DIR.is_dir():
        return []
    pending: list[Path] = []
    for p in sorted(JOBS_DIR.glob("*.json")):
        if p.name.endswith(".status.json"):
            continue
        status_p = JOBS_DIR / f"{p.stem}.status.json"
        if not status_p.exists():
            pending.append(p)
    return pending


def write_status(job_id: str, **fields) -> None:
    p = JOBS_DIR / f"{job_id}.status.json"
    cur: dict = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text())
        except Exception:
            cur = {}
    cur.update(fields)
    cur["id"] = job_id
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False))
        tmp.replace(p)
    except OSError:
        p.write_text(json.dumps(cur, indent=2, ensure_ascii=False))


def build_cmd(job_type: str, params: dict) -> list[str] | None:
    if job_type == "hls":
        cmd = ["hls-convert", str(LIBRARY_ROOT)]
        if params.get("filter"):
            cmd += ["--filter", str(params["filter"])]
        if params.get("force"):
            cmd += ["--force"]
        cmd += ["-w", str(int(params.get("workers", 2)))]
        return cmd
    if job_type == "ts-merge":
        cmd = ["ts-merge", str(LIBRARY_ROOT)]
        if params.get("filter"):
            cmd += ["--filter", str(params["filter"])]
        if params.get("delete"):
            cmd += ["--delete"]
        if params.get("force"):
            cmd += ["--force"]
        cmd += ["-w", str(int(params.get("workers", 2)))]
        return cmd
    return None


def run_job(spec_path: Path) -> None:
    try:
        spec = json.loads(spec_path.read_text())
    except Exception as exc:
        print(f"[{now_iso()}] invalid spec {spec_path}: {exc}", flush=True)
        return
    job_id = spec.get("id") or spec_path.stem
    job_type = spec.get("type", "hls")
    params = spec.get("params", {})
    log_path = JOBS_DIR / f"{job_id}.log"

    print(f"[{now_iso()}] start job {job_id} type={job_type}", flush=True)
    write_status(job_id, state="running", started_at=now_iso(), progress=0.0)

    cmd = build_cmd(job_type, params)
    if cmd is None:
        write_status(job_id, state="failed", finished_at=now_iso(),
                     error=f"unknown type: {job_type}")
        return

    completed = 0
    with log_path.open("ab", buffering=0) as log_f:
        log_f.write(f"# cmd: {' '.join(cmd)}\n".encode())
        log_f.write(f"# started_at: {now_iso()}\n".encode())
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                log_f.write(raw)
                line = raw.decode("utf-8", "replace")
                # 簡易進捗: 「完了:」「✅ 完了」を含む行でカウント
                if "✅" in line or "完了:" in line:
                    completed += 1
                    write_status(job_id, state="running",
                                 progress=min(0.99, completed / 100.0),
                                 stats={"completed": completed})
            proc.wait()
            rc = proc.returncode
        except Exception as exc:
            log_f.write(f"# exception: {exc}\n".encode())
            rc = -1

    if rc == 0:
        write_status(job_id, state="done", finished_at=now_iso(),
                     progress=1.0, stats={"completed": completed})
    else:
        write_status(job_id, state="failed", finished_at=now_iso(),
                     error=f"exit code {rc}", stats={"completed": completed})
    print(f"[{now_iso()}] done job {job_id} rc={rc}", flush=True)


def cleanup_old_jobs() -> None:
    if not JOBS_DIR.is_dir():
        return
    cutoff = time.time() - CLEANUP_AGE_HOURS * 3600
    for p in JOBS_DIR.glob("*.status.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("state") not in ("done", "failed"):
                continue
            fa = data.get("finished_at")
            if not fa:
                continue
            ts = datetime.fromisoformat(fa.replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                jid = data.get("id", p.stem.replace(".status", ""))
                for ext in (".json", ".status.json", ".log"):
                    (JOBS_DIR / f"{jid}{ext}").unlink(missing_ok=True)
        except Exception:
            pass


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{now_iso()}] converter ready, watching {JOBS_DIR}", flush=True)
    last_cleanup = 0.0
    while True:
        try:
            for j in find_pending_jobs():
                run_job(j)
            if time.time() - last_cleanup > 3600:
                cleanup_old_jobs()
                last_cleanup = time.time()
        except Exception as exc:
            print(f"[{now_iso()}] poll error: {exc}", flush=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
