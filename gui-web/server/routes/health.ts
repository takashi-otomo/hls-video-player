import { Hono } from 'hono';
import { existsSync, readdirSync, openSync, readSync, closeSync } from 'fs';
import { getLibraryRoot } from '../lib/settings';
import {
  driveConverted,
  mirrorConverted,
  resolveConverted,
  inMirror,
} from '../lib/hybrid';

export const health = new Hono();

// poster.png を実際に read してみて、Drive+Docker FUSE の EDEADLK
// (Resource deadlock avoided) が起きていないか自己診断する。
// ハイブリッド構成ではミラーが進むと読めるようになるため、結果は
// TTL 付きキャッシュ (一定間隔で再判定し、バナーが自動で消える)。
const PROBE_TTL_MS = 20_000;
let probeCache: {
  ok: boolean;
  reason: string;
  sampled: string | null;
} | null = null;
let probeAt = 0;

function probeFileRead(): { ok: boolean; reason: string; sampled: string | null } {
  if (probeCache && Date.now() - probeAt < PROBE_TTL_MS) return probeCache;
  const set = (r: { ok: boolean; reason: string; sampled: string | null }) => {
    probeCache = r;
    probeAt = Date.now();
    return r;
  };
  // 列挙は Drive + ミラーの和集合
  const dirs = [driveConverted(), mirrorConverted()].filter(Boolean) as string[];
  const stems = new Set<string>();
  for (const d of dirs) {
    if (!existsSync(d)) continue;
    try {
      for (const n of readdirSync(d)) if (!n.startsWith('.')) stems.add(n);
    } catch {
      /* readdir 失敗は無視 (他方で拾う) */
    }
  }
  if (stems.size === 0) {
    return set({ ok: true, reason: 'no converted dir yet', sampled: null });
  }
  // poster.png が在る stem を 1 件サンプリングして本文 read
  for (const stem of [...stems].sort().slice(0, 30)) {
    const poster = resolveConverted(`${stem}/thumbs/poster.png`);
    if (!existsSync(poster)) continue;
    try {
      // 先頭 8 バイトだけ読む (PNG マジック確認)。EDEADLK ならここで throw。
      const fd = openSync(poster, 'r');
      const buf = Buffer.alloc(8);
      const n = readSync(fd, buf, 0, 8, 0);
      closeSync(fd);
      if (n >= 8 && buf[0] === 0x89 && buf[1] === 0x50) {
        const via = inMirror(`${stem}/thumbs/poster.png`) ? 'mirror' : 'drive';
        return set({ ok: true, reason: `file read OK (${via})`, sampled: stem });
      }
      return set({
        ok: false,
        reason: `read returned ${n} bytes (not a PNG)`,
        sampled: stem,
      });
    } catch (e: any) {
      const msg = String(e?.message ?? e);
      const deadlock =
        msg.includes('EDEADLK') ||
        msg.includes('deadlock') ||
        msg.includes('Resource deadlock');
      return set({
        ok: false,
        reason: deadlock
          ? 'EDEADLK: Docker + Google Drive FUSE でファイル本文 read が deadlock。' +
            'ローカルミラー (make mirror) が未到達のファイルは読めません。' +
            'ミラーが進めば自動で表示されます。docs/troubleshoot.md 参照。'
          : `read failed: ${msg}`,
        sampled: stem,
      });
    }
  }
  return set({ ok: true, reason: 'no poster to probe', sampled: null });
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
