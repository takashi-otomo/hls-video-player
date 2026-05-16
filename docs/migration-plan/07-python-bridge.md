# 07. Python ツール連携 (Phase 2)

gui コンテナ (Bun) と converter コンテナ (Python) を **ファイルベースの job queue** で連携する。

## 7.1 設計方針

### 採用案: ファイルシステム上の queue
- gui が `<LIBRARY_ROOT>/.jobs/<id>.json` に job spec を書く
- converter が定期 polling で検知 → 実行 → ステータス更新
- ログは `<LIBRARY_ROOT>/.jobs/<id>.log` に append、gui が tail して WebSocket で配信

### なぜこの方式か
- **Docker socket を gui に渡さない**: セキュリティ的に安全
- **共有 volume だけで完結**: 追加のメッセージブローカー (Redis 等) 不要
- **シンプル**: 100 行未満で実装できる
- **永続性**: コンテナ再起動でも job 履歴が残る

### 代替案との比較

| 方式 | 利点 | 欠点 |
|---|---|---|
| **ファイル queue** (採用) | 依存ゼロ、検査・デバッグ容易 | polling 遅延 (~1 秒) |
| docker socket 経由 | リアルタイム | gui に privileged 権限必要、セキュリティリスク |
| Redis / RabbitMQ | 本格的、スケール可 | 3 つ目のコンテナ、複雑 |
| HTTP RPC (converter が server) | リアルタイム、構造化 | converter 側に Flask 等が必要 |

将来スケールしたくなったら HTTP RPC または Redis に差し替える。

## 7.2 ファイル構造

```
<LIBRARY_ROOT>/
└── .jobs/
    ├── 01J9ABCDEF.json         ← job spec (gui が書く)
    ├── 01J9ABCDEF.status.json  ← 進捗 (converter が書く)
    ├── 01J9ABCDEF.log          ← stdout/stderr append
    └── 01J9XYZQRS.json         ← 別 job
```

### job spec (gui 書き込み)
```json
{
  "id": "01J9ABCDEF",
  "type": "hls",
  "created_at": "2026-05-16T10:00:00Z",
  "params": {
    "filter": "abc",
    "force": false,
    "workers": 2
  }
}
```

`type` は `"hls"` (HLS 変換) または `"ts-merge"` (TS結合)。

### status (converter 書き込み、頻繁に更新)
```json
{
  "id": "01J9ABCDEF",
  "state": "running",
  "started_at": "2026-05-16T10:00:01Z",
  "finished_at": null,
  "progress": 0.42,
  "current_target": "video-x.mp4",
  "stats": { "completed": 5, "skipped": 1, "error": 0 }
}
```

state: `"queued" | "running" | "done" | "failed"`

## 7.3 converter コンテナ実装

### `docker/converter-entry.py`

```python
#!/usr/bin/env python3
"""converter コンテナの entry point: <LIBRARY_ROOT>/.jobs/ を polling して
新規 job spec を見つけたら type に応じて実行する。"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

LIBRARY_ROOT = Path(os.environ.get("LIBRARY_ROOT", "/library"))
JOBS_DIR = LIBRARY_ROOT / ".jobs"
POLL_INTERVAL = 1.0  # 秒

def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

def find_pending_jobs() -> list[Path]:
    """spec はあるが status が無い (= 未処理) の job を返す。"""
    if not JOBS_DIR.is_dir():
        return []
    pending = []
    for p in sorted(JOBS_DIR.glob("*.json")):
        if p.name.endswith(".status.json"):
            continue
        status_p = JOBS_DIR / f"{p.stem}.status.json"
        if not status_p.exists():
            pending.append(p)
    return pending

def write_status(job_id: str, **fields) -> None:
    """status を atomic update。"""
    p = JOBS_DIR / f"{job_id}.status.json"
    cur = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text())
        except Exception:
            cur = {}
    cur.update(fields)
    cur["id"] = job_id
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False))
    tmp.replace(p)

def run_job(spec_path: Path) -> None:
    spec = json.loads(spec_path.read_text())
    job_id = spec["id"]
    job_type = spec["type"]
    params = spec.get("params", {})
    log_path = JOBS_DIR / f"{job_id}.log"

    print(f"[{now_iso()}] start job {job_id} type={job_type}", flush=True)
    write_status(job_id, state="running", started_at=now_iso(), progress=0.0)

    # コマンド組み立て
    if job_type == "hls":
        cmd = ["hls-convert", str(LIBRARY_ROOT)]
        if params.get("filter"):
            cmd += ["--filter", params["filter"]]
        if params.get("force"):
            cmd += ["--force"]
        cmd += ["-w", str(params.get("workers", 2))]
    elif job_type == "ts-merge":
        cmd = ["ts-merge", str(LIBRARY_ROOT)]
        if params.get("filter"):
            cmd += ["--filter", params["filter"]]
        if params.get("delete"):
            cmd += ["--delete"]
        cmd += ["-w", str(params.get("workers", 2))]
    else:
        write_status(job_id, state="failed", finished_at=now_iso(),
                     error=f"unknown type: {job_type}")
        return

    # 実行 + ログ append
    with log_path.open("ab", buffering=0) as log_f:
        log_f.write(f"# cmd: {' '.join(cmd)}\n".encode())
        log_f.write(f"# started_at: {now_iso()}\n".encode())
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, b""):
                log_f.write(line)
                # progress 推定 (簡易: 「完了:」を含む行で +1)
                # 必要なら hls-convert / ts-merge 側に --json-progress 追加
            proc.wait()
            rc = proc.returncode
        except Exception as exc:
            log_f.write(f"# exception: {exc}\n".encode())
            rc = -1

    if rc == 0:
        write_status(job_id, state="done", finished_at=now_iso(), progress=1.0)
    else:
        write_status(job_id, state="failed", finished_at=now_iso(),
                     error=f"exit code {rc}")
    print(f"[{now_iso()}] done job {job_id} rc={rc}", flush=True)

def main():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{now_iso()}] converter ready, watching {JOBS_DIR}", flush=True)
    while True:
        try:
            jobs = find_pending_jobs()
            for j in jobs:
                run_job(j)
        except Exception as exc:
            print(f"[{now_iso()}] poll error: {exc}", flush=True)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
```

## 7.4 gui コンテナ側 (Bun) 実装

### `gui-web/server/lib/job-queue.ts`

```typescript
import { writeFileSync, readFileSync, existsSync, watchFile, unwatchFile } from 'fs';
import { join } from 'path';
import { mkdir } from 'fs/promises';
import { getLibraryRoot } from './settings';

export interface JobSpec {
  id: string;
  type: 'hls' | 'ts-merge';
  created_at: string;
  params: Record<string, any>;
}

export interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  started_at?: string;
  finished_at?: string;
  progress?: number;
  error?: string;
  current_target?: string;
}

function jobsDir(): string {
  return join(getLibraryRoot(), '.jobs');
}

function newJobId(): string {
  // ULID 風: タイムスタンプ + ランダム
  const t = Date.now().toString(36).toUpperCase().padStart(10, '0');
  const r = Math.random().toString(36).slice(2, 10).toUpperCase();
  return `${t}${r}`;
}

export async function enqueue(spec: Omit<JobSpec, 'id' | 'created_at'>): Promise<JobSpec> {
  await mkdir(jobsDir(), { recursive: true });
  const full: JobSpec = {
    id: newJobId(),
    created_at: new Date().toISOString(),
    ...spec,
  };
  const p = join(jobsDir(), `${full.id}.json`);
  writeFileSync(p, JSON.stringify(full, null, 2));
  return full;
}

export function getStatus(jobId: string): JobStatus | null {
  const p = join(jobsDir(), `${jobId}.status.json`);
  if (!existsSync(p)) {
    // spec はあるが status まだ → "queued"
    const specP = join(jobsDir(), `${jobId}.json`);
    if (existsSync(specP)) return { id: jobId, state: 'queued' };
    return null;
  }
  try {
    return JSON.parse(readFileSync(p, 'utf-8'));
  } catch {
    return null;
  }
}

export function getLogPath(jobId: string): string {
  return join(jobsDir(), `${jobId}.log`);
}
```

### `gui-web/server/routes/convert.ts`

```typescript
import { Hono } from 'hono';
import { upgradeWebSocket } from 'hono/bun';
import { enqueue, getStatus, getLogPath } from '../lib/job-queue';
import { watch, statSync, openSync, readSync, closeSync } from 'fs';

export const convert = new Hono();

convert.post('/start', async (c) => {
  const body = await c.req.json();
  const spec = await enqueue({
    type: body.type ?? 'hls',
    params: {
      filter: body.filter,
      force: body.force ?? false,
      workers: body.workers ?? 2,
      delete: body.delete ?? false,
    },
  });
  return c.json({ ok: true, job_id: spec.id });
});

convert.get('/jobs/:id', (c) => {
  const status = getStatus(c.req.param('id'));
  if (!status) return c.json({ error: 'not_found' }, 404);
  return c.json(status);
});

// WebSocket: ログ streaming
convert.get('/jobs/:id/logs', upgradeWebSocket((c) => {
  const jobId = c.req.param('id');
  const logPath = getLogPath(jobId);
  let pos = 0;
  let watcher: any = null;

  return {
    onOpen(_evt, ws) {
      // 既存ログをまず一気に送る
      try { pos = statSync(logPath).size; } catch { pos = 0; }
      try {
        const fd = openSync(logPath, 'r');
        const buf = Buffer.alloc(pos);
        readSync(fd, buf, 0, pos, 0);
        closeSync(fd);
        ws.send(JSON.stringify({ type: 'log', text: buf.toString('utf-8') }));
      } catch {}

      // 以降は変更を watch して差分だけ送る
      watcher = watch(logPath, { persistent: false }, () => {
        try {
          const newSize = statSync(logPath).size;
          if (newSize > pos) {
            const fd = openSync(logPath, 'r');
            const len = newSize - pos;
            const buf = Buffer.alloc(len);
            readSync(fd, buf, 0, len, pos);
            closeSync(fd);
            pos = newSize;
            ws.send(JSON.stringify({ type: 'log', text: buf.toString('utf-8') }));
          }
        } catch (e) {
          ws.send(JSON.stringify({ type: 'error', message: String(e) }));
        }
        // status も併送
        const status = getStatus(jobId);
        if (status) ws.send(JSON.stringify({ type: 'status', ...status }));
      });
    },
    onClose() {
      if (watcher) try { watcher.close(); } catch {}
    },
  };
}));
```

## 7.5 フロントエンド: ConvertPanel.svelte (Phase 2)

```svelte
<script lang="ts">
  let logLines = '';
  let status: any = null;
  let jobId: string | null = null;
  let ws: WebSocket | null = null;

  async function startHlsConvert() {
    const r = await fetch('/api/convert/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ type: 'hls', workers: 2 }),
    });
    const { job_id } = await r.json();
    jobId = job_id;
    logLines = '';
    // WS で log + status を購読
    ws = new WebSocket(`ws://${location.host}/api/convert/jobs/${job_id}/logs`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === 'log') logLines += m.text;
      else if (m.type === 'status') status = m;
    };
  }

  function stop() {
    if (ws) ws.close();
    ws = null;
  }
</script>

<button on:click={startHlsConvert} disabled={status?.state === 'running'}>
  🎬 HLS 変換実行
</button>

{#if status}
  <div class="status">
    状態: {status.state} {status.progress ? `(${Math.round(status.progress * 100)}%)` : ''}
  </div>
{/if}

<pre class="log">{logLines}</pre>

<style>
  .log { max-height: 300px; overflow-y: auto; background: #0a0c10;
         padding: 8px; font-family: Menlo, monospace; font-size: 11px; }
</style>
```

## 7.6 進捗の精度向上 (任意)

現状 `hls-convert` は人間向けログのみ出力。converter コンテナ側で `# PROGRESS 0.42` のような行を正規表現で拾うか、Python CLI に `--json-progress` を追加すると進捗バーがより正確になる。

```python
# library_cli.py に追加 (例)
if args.json_progress:
    print(json.dumps({"event": "progress", "done": done, "total": total}), flush=True)
```

ただし MVP では進捗バー無しでもログだけ見えれば十分。Phase 3 で対応。

## 7.7 デバッグ

```bash
# job spec を直接書き込んで動作確認
echo '{"id":"test01","type":"hls","created_at":"...","params":{"filter":"abc","workers":1}}' \
  > /Users/takashi/.../myfans_見放題/.jobs/test01.json

# converter コンテナのログを見る
docker compose logs -f converter

# 数秒後に status.json と log が現れる
ls /Users/takashi/.../myfans_見放題/.jobs/
# test01.json  test01.status.json  test01.log
```

## 7.8 古い job の cleanup

`.jobs/` がたまりっぱなしになる。converter 側で起動時に 24 時間以上前の done job を削除する処理を入れる。

```python
def cleanup_old_jobs(max_age_hours: int = 24) -> None:
    cutoff = time.time() - max_age_hours * 3600
    for p in JOBS_DIR.glob("*.status.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("state") not in ("done", "failed"):
                continue
            if data.get("finished_at"):
                # finished_at が cutoff より古いなら削除
                ft = datetime.fromisoformat(data["finished_at"].replace("Z", "+00:00")).timestamp()
                if ft < cutoff:
                    p.unlink(missing_ok=True)
                    (JOBS_DIR / f"{data['id']}.json").unlink(missing_ok=True)
                    (JOBS_DIR / f"{data['id']}.log").unlink(missing_ok=True)
        except Exception:
            pass
```

## 7.9 セキュリティ考慮

- gui コンテナは `LIBRARY_ROOT/.jobs/` の書き込み権限が必要
- converter コンテナも同じ
- ホストへのコマンドインジェクション防止: `params.filter` 等は subprocess の引数として渡す (shell 不通)
- 不正な job type は converter 側で reject

## 7.10 Phase 2 で実装する順序

1. `docker/converter-entry.py` を書く (Day 1)
2. `gui-web/server/lib/job-queue.ts` (Day 2)
3. `gui-web/server/routes/convert.ts` (POST /start, GET /jobs/:id) (Day 2)
4. ConvertPanel.svelte の skeleton (Day 3)
5. WebSocket でログ streaming (Day 4-5)
6. status 表示 + 進捗バー (Day 5)
7. 結合テスト (Day 6)
8. UI 仕上げ (Day 7-10)
