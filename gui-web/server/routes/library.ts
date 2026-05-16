// /library/* — converted/ 配下を動的に配信
// 画像 (poster.png / thumb_*.jpg) はローカルディスクキャッシュ + ETag/304。
// HLS (.m3u8 / .ts) は streaming のまま (大きい / 既に immutable)。
import { Hono } from 'hono';
import { statSync } from 'fs';
import { join, normalize, sep } from 'path';
import { getLibraryRoot, convertedDirName } from '../lib/settings';
import { serveCached } from '../lib/file-cache';

export const library = new Hono();

const MIME: Record<string, string> = {
  '.m3u8': 'application/vnd.apple.mpegurl',
  '.ts': 'video/mp2t',
  '.vtt': 'text/vtt',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.json': 'application/json',
};

const CACHE: Record<string, string> = {
  '.ts': 'public, max-age=31536000, immutable',
  '.png': 'public, max-age=86400',
  '.jpg': 'public, max-age=86400',
  '.jpeg': 'public, max-age=86400',
  '.m3u8': 'no-cache',
};

// ディスクキャッシュ対象 (小さく頻繁にアクセスされるもの)
const CACHEABLE = new Set(['.png', '.jpg', '.jpeg']);

library.get('/*', (c) => {
  const url = new URL(c.req.url);
  const rel = decodeURIComponent(url.pathname.replace(/^\/library\//, ''));
  if (rel.split('/').includes('..')) {
    return c.json({ error: 'invalid path' }, 400);
  }
  const base = normalize(join(getLibraryRoot(), convertedDirName()));
  const target = normalize(join(base, rel));
  if (target !== base && !target.startsWith(base + sep)) {
    return c.json({ error: 'forbidden' }, 403);
  }

  const dot = target.lastIndexOf('.');
  const ext = dot >= 0 ? target.slice(dot).toLowerCase() : '';
  const mime = MIME[ext] ?? 'application/octet-stream';

  // --- 画像: ディスクキャッシュ + ETag/304 ---
  if (CACHEABLE.has(ext)) {
    const ifNoneMatch = c.req.header('if-none-match') ?? null;
    const result = serveCached(rel, target, ifNoneMatch);
    if (!result) return c.json({ error: 'not_found' }, 404);
    const headers: Record<string, string> = {
      'Content-Type': mime,
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': CACHE[ext] ?? 'public, max-age=86400',
      ETag: result.etag,
    };
    if (result.notModified) {
      return new Response(null, { status: 304, headers });
    }
    // server は Bun ランタイムで動くため Response の BodyInit は Buffer/
    // Uint8Array を受け付ける。svelte-check は DOM lib で型を見るため
    // 不整合になるが実行時は問題ない (Bun.file().stream() も同様に ts-ignore)。
    // @ts-ignore Bun Response accepts Buffer
    return new Response(result.body, { headers });
  }

  // --- HLS 等: streaming のまま ---
  try {
    if (!statSync(target).isFile()) {
      return c.json({ error: 'not_found' }, 404);
    }
  } catch {
    return c.json({ error: 'not_found' }, 404);
  }
  const headers: Record<string, string> = {
    'Content-Type': mime,
    'Access-Control-Allow-Origin': '*',
  };
  if (CACHE[ext]) headers['Cache-Control'] = CACHE[ext];
  // @ts-ignore Bun global
  return new Response(Bun.file(target).stream(), { headers });
});
