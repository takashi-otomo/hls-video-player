// /library/* — converted/ 配下を動的に配信
import { Hono } from 'hono';
import { statSync } from 'fs';
import { join, normalize, sep } from 'path';
import { getLibraryRoot, convertedDirName } from '../lib/settings';

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
  try {
    if (!statSync(target).isFile()) {
      return c.json({ error: 'not_found' }, 404);
    }
  } catch {
    return c.json({ error: 'not_found' }, 404);
  }
  const dot = target.lastIndexOf('.');
  const ext = dot >= 0 ? target.slice(dot).toLowerCase() : '';
  const mime = MIME[ext] ?? 'application/octet-stream';
  const headers: Record<string, string> = {
    'Content-Type': mime,
    'Access-Control-Allow-Origin': '*',
  };
  if (CACHE[ext]) headers['Cache-Control'] = CACHE[ext];
  // Bun.file().stream() で zero-copy 配信
  // @ts-ignore - Bun global
  return new Response(Bun.file(target).stream(), { headers });
});
