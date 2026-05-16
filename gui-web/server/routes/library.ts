// /library/* — converted/ 配下を「ハイブリッド」配信。
//   1. ローカルミラー (MIRROR_ROOT) に在ればそこから直接 stream (高速・確実)
//   2. 無ければ Drive にフォールバック。画像/HLS は serveCached 経由
//      (cache-first。Drive 本文 read が EDEADLK なら 404 → クライアントは
//       ローディング表示。ミラーが進めば次回からローカル配信に切替)
import { Hono } from 'hono';
import { statSync } from 'fs';
import { join, normalize, sep } from 'path';
import { serveCached } from '../lib/file-cache';
import { driveConverted, mirrorConverted } from '../lib/hybrid';

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

// Drive フォールバック時にディスクキャッシュ対象とする拡張子。
const CACHEABLE = new Set(['.png', '.jpg', '.jpeg', '.m3u8', '.ts', '.vtt']);

function within(base: string, target: string): boolean {
  return target === base || target.startsWith(base + sep);
}

library.get('/*', (c) => {
  const url = new URL(c.req.url);
  const rel = decodeURIComponent(url.pathname.replace(/^\/library\//, ''));
  if (rel.split('/').includes('..')) {
    return c.json({ error: 'invalid path' }, 400);
  }

  const driveBase = normalize(driveConverted());
  const driveTarget = normalize(join(driveBase, rel));
  if (!within(driveBase, driveTarget)) {
    return c.json({ error: 'forbidden' }, 403);
  }
  const mc = mirrorConverted();
  const mirrorBase = mc ? normalize(mc) : null;
  const mirrorTarget = mirrorBase ? normalize(join(mirrorBase, rel)) : null;

  const dot = driveTarget.lastIndexOf('.');
  const ext = dot >= 0 ? driveTarget.slice(dot).toLowerCase() : '';
  const mime = MIME[ext] ?? 'application/octet-stream';
  const ifNoneMatch = c.req.header('if-none-match') ?? null;

  // --- 1) ローカルミラーに在れば最優先で直接配信 ---
  if (mirrorTarget && mirrorBase && within(mirrorBase, mirrorTarget)) {
    let st;
    try {
      st = statSync(mirrorTarget);
    } catch {
      st = null;
    }
    if (st && st.isFile()) {
      const etag = `"${st.size}-${Math.floor(st.mtimeMs)}"`;
      const headers: Record<string, string> = {
        'Content-Type': mime,
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': CACHE[ext] ?? 'public, max-age=86400',
        ETag: etag,
      };
      if (ifNoneMatch && ifNoneMatch === etag) {
        return new Response(null, { status: 304, headers });
      }
      // @ts-ignore Bun global
      return new Response(Bun.file(mirrorTarget).stream(), { headers });
    }
  }

  // --- 2) Drive フォールバック (画像/HLS は cache-first) ---
  if (CACHEABLE.has(ext)) {
    const result = serveCached(rel, driveTarget, ifNoneMatch);
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
    // @ts-ignore Bun Response accepts Buffer
    return new Response(result.body, { headers });
  }

  // --- それ以外 (想定外の大きいバイナリ等): streaming フォールバック ---
  try {
    if (!statSync(driveTarget).isFile()) {
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
  return new Response(Bun.file(driveTarget).stream(), { headers });
});
