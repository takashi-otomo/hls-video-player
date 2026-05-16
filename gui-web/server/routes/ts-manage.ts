// /api/ts — TS結合管理 (Phase 2)
import { Hono } from 'hono';
import { tsStatus, addToIndex, removeFromIndex } from '../lib/ts-status';

export const tsManage = new Hono();

tsManage.get('/status', (c) => {
  try {
    return c.json(tsStatus());
  } catch (e) {
    console.error('tsStatus failed', e);
    return c.json({ error: String(e) }, 500);
  }
});

tsManage.post('/index/add', async (c) => {
  let body: { urls?: string[] };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid JSON' }, 400);
  }
  if (!Array.isArray(body.urls)) {
    return c.json({ error: 'urls must be array' }, 400);
  }
  const r = addToIndex(body.urls);
  return c.json({ ok: true, ...r });
});

tsManage.delete('/index/:uuid', (c) => {
  const removed = removeFromIndex([c.req.param('uuid')]);
  return c.json({ ok: true, removed });
});

tsManage.post('/index/remove', async (c) => {
  let body: { uuids?: string[] };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: 'invalid JSON' }, 400);
  }
  const removed = removeFromIndex(body.uuids ?? []);
  return c.json({ ok: true, removed });
});
