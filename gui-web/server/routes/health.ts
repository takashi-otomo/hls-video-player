import { Hono } from 'hono';
import { existsSync, readdirSync, readFileSync, openSync, readSync, closeSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot, convertedDirName } from '../lib/settings';

export const health = new Hono();

// 1 件の poster.png / m3u8 を実際に read してみて、Drive+Docker FUSE の
// EDEADLK (Resource deadlock avoided) 問題が起きていないか自己診断する。
// 結果はキャッシュ (起動毎に 1 回だけ判定すれば十分)。
let probeCache: {
  ok: boolean;
  reason: string;
  sampled: string | null;
} | null = null;

function probeFileRead(): { ok: boolean; reason: string; sampled: string | null } {
  if (probeCache) return probeCache;
  const root = join(getLibraryRoot(), convertedDirName());
  if (!existsSync(root)) {
    probeCache = { ok: true, reason: 'no converted dir yet', sampled: null };
    return probeCache;
  }
  let stems: string[];
  try {
    stems = readdirSync(root).filter((n) => !n.startsWith('.'));
  } catch (e) {
    probeCache = { ok: false, reason: `readdir failed: ${e}`, sampled: null };
    return probeCache;
  }
  // 最初に poster.png が存在する stem を 1 件サンプリングして本文 read
  for (const stem of stems.slice(0, 30)) {
    const poster = join(root, stem, 'thumbs', 'poster.png');
    if (!existsSync(poster)) continue;
    try {
      // 先頭 8 バイトだけ読む (PNG マジック確認)。EDEADLK ならここで throw。
      const fd = openSync(poster, 'r');
      const buf = Buffer.alloc(8);
      const n = readSync(fd, buf, 0, 8, 0);
      closeSync(fd);
      if (n >= 8 && buf[0] === 0x89 && buf[1] === 0x50) {
        probeCache = { ok: true, reason: 'file read OK', sampled: stem };
        return probeCache;
      }
      probeCache = {
        ok: false,
        reason: `read returned ${n} bytes (not a PNG)`,
        sampled: stem,
      };
      return probeCache;
    } catch (e: any) {
      const msg = String(e?.message ?? e);
      const deadlock =
        msg.includes('EDEADLK') ||
        msg.includes('deadlock') ||
        msg.includes('Resource deadlock');
      probeCache = {
        ok: false,
        reason: deadlock
          ? 'EDEADLK: Docker + Google Drive FUSE でファイル本文 read が deadlock しています。' +
            'ローカルフォルダ (Drive 外) を LIBRARY_PATH に指定するか、' +
            'Python 版 (ts-merge --gui) をご利用ください。docs/troubleshoot.md 参照。'
          : `read failed: ${msg}`,
        sampled: stem,
      };
      return probeCache;
    }
  }
  probeCache = { ok: true, reason: 'no poster to probe', sampled: null };
  return probeCache;
}

health.get('/', (c) => {
  const lib = getLibraryRoot();
  const probe = probeFileRead();
  return c.json({
    ok: true,
    library_root: lib,
    library_root_exists: existsSync(lib),
    file_read: {
      ok: probe.ok,
      reason: probe.reason,
      sampled_stem: probe.sampled,
    },
  });
});
