// /api/convert — HLS変換 / TS結合ジョブ
import { Hono } from 'hono';
import { enqueue, getStatus, getLogPath } from '../lib/job-queue';
import { statSync, openSync, readSync, closeSync } from 'fs';

export const convert = new Hono();

convert.post('/start', async (c) => {
  let body: any = {};
  try {
    body = await c.req.json();
  } catch {
    body = {};
  }
  const spec = await enqueue({
    type: body.type === 'ts-merge' ? 'ts-merge' : 'hls',
    params: {
      filter: body.filter ?? '',
      force: !!body.force,
      workers: Number(body.workers) || 2,
      delete: !!body.delete,
    },
  });
  return c.json({ ok: true, job_id: spec.id });
});

convert.get('/jobs/:id', (c) => {
  const status = getStatus(c.req.param('id'));
  if (!status) return c.json({ error: 'not_found' }, 404);
  return c.json(status);
});

// WebSocket upgrade は index.ts の Bun.serve fetch で先取りされるので
// ここではルートを定義しない。WS ハンドラだけ export する。

// Bun.serve に渡す WebSocket ハンドラ
export const wsHandlers = {
  open(ws: any) {
    const { logPath } = ws.data;
    ws.data.pos = 0;
    try {
      ws.data.pos = statSync(logPath).size;
      const fd = openSync(logPath, 'r');
      const buf = Buffer.alloc(ws.data.pos);
      readSync(fd, buf, 0, ws.data.pos, 0);
      closeSync(fd);
      ws.send(JSON.stringify({ type: 'log', text: buf.toString('utf-8') }));
    } catch {
      /* ログ未生成 */
    }
    // Drive FUSE で fs.watch が不安定なため定期 poll で差分送信
    ws.data.timer = setInterval(() => {
      try {
        const size = statSync(logPath).size;
        if (size > ws.data.pos) {
          const fd = openSync(logPath, 'r');
          const len = size - ws.data.pos;
          const buf = Buffer.alloc(len);
          readSync(fd, buf, 0, len, ws.data.pos);
          closeSync(fd);
          ws.data.pos = size;
          ws.send(JSON.stringify({ type: 'log', text: buf.toString('utf-8') }));
        }
      } catch {
        /* まだ無い */
      }
      const st = getStatus(ws.data.jobId);
      if (st) {
        ws.send(JSON.stringify({ type: 'status', ...st }));
        if (st.state === 'done' || st.state === 'failed') {
          clearInterval(ws.data.timer);
        }
      }
    }, 1000);
  },
  message() {
    /* クライアントからの受信は不要 */
  },
  close(ws: any) {
    if (ws.data?.timer) clearInterval(ws.data.timer);
  },
};
