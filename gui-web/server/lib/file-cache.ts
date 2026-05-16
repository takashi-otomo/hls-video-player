// サムネ等の小ファイルをローカルディスクにキャッシュする。
// Drive FUSE は初回 read が遅い (download 待ち) ため、一度読んだら
// CACHE_DIR (ローカル volume = 高速 SSD) に複写して以降はそこから配信する。
//
// キャッシュ鍵: 相対パス + 元ファイルの size/mtime。
// 元ファイルが再変換などで変わったら size/mtime が変わり、自動的に
// 古いキャッシュは無視されて再生成される。
import {
  existsSync,
  statSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  renameSync,
  readdirSync,
} from 'fs';
import { join } from 'path';
import { createHash } from 'crypto';

const CACHE_DIR = process.env.CACHE_DIR ?? '/cache';

// 相対パス -> { etag, cachePath } の in-memory index。
// プロセス内で同じファイルへの再アクセス時に stat を 1 回省ける。
const memIndex = new Map<string, { etag: string; cachePath: string }>();

let cacheDirReady = false;
function ensureCacheDir() {
  if (cacheDirReady) return;
  try {
    mkdirSync(CACHE_DIR, { recursive: true });
  } catch {
    /* read-only 等。その場合キャッシュは無効化される */
  }
  cacheDirReady = true;
}

function keyFor(relPath: string): string {
  return createHash('sha1').update(relPath).digest('hex');
}

/**
 * 元ファイルが読めない (Drive FUSE 未 materialise 等) ときに、
 * 過去にキャッシュした任意のバージョンを返すフォールバック。
 * 無ければ null (= 呼び出し側で 404)。
 */
function staleFallback(relPath: string): CachedResult | null {
  // 1) メモリ index
  const mem = memIndex.get(relPath);
  if (mem && existsSync(mem.cachePath)) {
    try {
      return { body: readFileSync(mem.cachePath), etag: mem.etag, notModified: false };
    } catch {
      /* fall through */
    }
  }
  // 2) ディスクキャッシュを prefix で走査 (`<hash>_<size>_<mtime>`)
  const prefix = keyFor(relPath) + '_';
  try {
    const cands = readdirSync(CACHE_DIR)
      .filter((n) => n.startsWith(prefix) && !n.endsWith('.tmp'))
      .sort();
    if (cands.length > 0) {
      const last = cands[cands.length - 1]; // 最新 mtime のもの
      const cachePath = join(CACHE_DIR, last);
      const m = last.slice(prefix.length).split('_');
      const etag = m.length >= 2 ? `"${m[0]}-${m[1]}"` : `"stale"`;
      memIndex.set(relPath, { etag, cachePath });
      return { body: readFileSync(cachePath), etag, notModified: false };
    }
  } catch {
    /* CACHE_DIR が無い等 */
  }
  return null;
}

export interface CachedResult {
  /** 配信すべきバイト列 */
  body: Buffer;
  /** ETag (size-mtimeMs) */
  etag: string;
  /** クライアントの If-None-Match と一致したか (= 304 を返してよい) */
  notModified: boolean;
}

/**
 * src (Drive FUSE 上のファイル) を、ローカルキャッシュ経由で取得する。
 *
 * - 元ファイルを 1 回 stat (Drive FUSE でも stat は read より遥かに軽い)
 * - etag = `${size}-${mtimeMs}` を計算
 * - If-None-Match が一致 → notModified=true (本文不要、304 にできる)
 * - キャッシュに同 etag の本文があれば local から読む (高速)
 * - 無ければ Drive から 1 回 read → cache に書く → 返す
 */
export function serveCached(
  relPath: string,
  srcPath: string,
  ifNoneMatch: string | null,
): CachedResult | null {
  let st;
  try {
    st = statSync(srcPath);
    if (!st.isFile()) return staleFallback(relPath);
  } catch {
    // Drive FUSE が未 materialise / ECANCELED 等で stat 失敗。
    // 過去に一度でもキャッシュできていればそれを返す (404 を避ける)。
    return staleFallback(relPath);
  }

  const etag = `"${st.size}-${Math.floor(st.mtimeMs)}"`;
  if (ifNoneMatch && ifNoneMatch === etag) {
    return { body: Buffer.alloc(0), etag, notModified: true };
  }

  ensureCacheDir();
  const cachePath = join(CACHE_DIR, `${keyFor(relPath)}_${st.size}_${Math.floor(st.mtimeMs)}`);

  // メモリ index に同 etag があれば cache から即配信
  const mem = memIndex.get(relPath);
  if (mem && mem.etag === etag && existsSync(mem.cachePath)) {
    try {
      return { body: readFileSync(mem.cachePath), etag, notModified: false };
    } catch {
      /* fall through */
    }
  }

  // ディスクキャッシュにヒット
  if (existsSync(cachePath)) {
    try {
      const body = readFileSync(cachePath);
      memIndex.set(relPath, { etag, cachePath });
      return { body, etag, notModified: false };
    } catch {
      /* 壊れていたら作り直す */
    }
  }

  // キャッシュミス: Drive FUSE から 1 回だけ読む
  let body: Buffer;
  try {
    body = readFileSync(srcPath);
  } catch {
    return null;
  }

  // cache へ atomic 書き込み (失敗しても配信は継続)
  try {
    const tmp = cachePath + '.tmp';
    writeFileSync(tmp, body);
    renameSync(tmp, cachePath);
    memIndex.set(relPath, { etag, cachePath });
  } catch {
    /* cache 書けなくても OK */
  }

  return { body, etag, notModified: false };
}
