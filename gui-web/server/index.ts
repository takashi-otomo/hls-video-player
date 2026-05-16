// Bun + Hono サーバ。/api/* と /library/* を提供し、それ以外は SPA を返す。
import { Hono } from 'hono';
import { logger } from 'hono/logger';
import { existsSync, statSync } from 'fs';
import { join, normalize } from 'path';
import { health } from './routes/health';
import { settings } from './routes/settings';
import { videos } from './routes/videos';
import { favorites } from './routes/favorites';
import { library } from './routes/library';
import { convert, wsHandlers } from './routes/convert';
import { tsManage } from './routes/ts-manage';
import { getLogPath } from './lib/job-queue';

const app = new Hono();
app.use('*', logger());

// --- API ---
app.route('/api/health', health);
app.route('/api/settings', settings);
app.route('/api/videos', videos);
app.route('/api/favorites', favorites);
app.route('/api/convert', convert);
app.route('/api/ts', tsManage);

// --- 動的ライブラリ配信 ---
app.route('/library', library);

// --- SPA 静的配信 (dist/) + フォールバック ---
// Dockerfile は WORKDIR /app で `bun run server/index.ts` を実行するので
// cwd は /app、dist は /app/dist。DIST_DIR 環境変数で上書き可。
const DIST = process.env.DIST_DIR ?? join(process.cwd(), 'dist');
const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.webmanifest': 'application/manifest+json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

app.get('/*', (c) => {
  const url = new URL(c.req.url);
  let path = decodeURIComponent(url.pathname);
  if (path === '/' || path === '') path = '/index.html';

  const candidate = normalize(join(DIST, path));
  if (!candidate.startsWith(DIST)) return c.text('forbidden', 403);

  if (existsSync(candidate) && statSync(candidate).isFile()) {
    const dot = candidate.lastIndexOf('.');
    const ext = dot >= 0 ? candidate.slice(dot).toLowerCase() : '';
    // @ts-ignore Bun global
    return new Response(Bun.file(candidate).stream(), {
      headers: { 'Content-Type': MIME[ext] ?? 'application/octet-stream' },
    });
  }

  // SPA フォールバック (hash ルーティングなので実質 / のみ)
  const indexHtml = join(DIST, 'index.html');
  if (existsSync(indexHtml)) {
    // @ts-ignore Bun global
    return new Response(Bun.file(indexHtml).stream(), {
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    });
  }
  return c.text('SPA not built. Run `bun run build`.', 503);
});

const PORT = Number(process.env.PORT ?? 7860);

// @ts-ignore Bun global
const server = Bun.serve({
  port: PORT,
  hostname: '0.0.0.0',
  async fetch(req: Request, srv: any) {
    const u = new URL(req.url);
    // WebSocket upgrade: /api/convert/jobs/:id/logs
    const wsMatch = u.pathname.match(
      /^\/api\/convert\/jobs\/([^/]+)\/logs$/,
    );
    if (
      wsMatch &&
      req.headers.get('upgrade')?.toLowerCase() === 'websocket'
    ) {
      const jobId = decodeURIComponent(wsMatch[1]);
      const ok = srv.upgrade(req, {
        data: { jobId, logPath: getLogPath(jobId), pos: 0 },
      });
      if (ok) return undefined;
      return new Response('WebSocket upgrade failed', { status: 426 });
    }
    return app.fetch(req, { server: srv });
  },
  websocket: wsHandlers,
});

console.log(`hls-gui listening on http://0.0.0.0:${PORT}`);
// 注意: `export default server` を書くと Bun が再度 Bun.serve() を呼んで
// EADDRINUSE になるため、ここでは default export しない。
void server;
