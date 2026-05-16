// サムネ等の小ファイルをローカルディスクにキャッシュする。
//
// 方針 (キャッシュ優先):
//   - キャッシュがあれば「キャッシュを読む」。元ファイル (Drive FUSE) には
//     一切触れない (stat も read もしない)。
//     → Docker+Drive の EDEADLK を踏まない / 高速。
//   - キャッシュが無ければ「実ファイルを読む」。読めたらキャッシュへ複写し、
//     以降はキャッシュ側から配信する。
//
// キャッシュ鍵は相対パスのみ (sha1(relPath))。converted/ 配下の出力は
// 一度生成されたら不変なので size/mtime は鍵に含めない。再変換などで
// 元が変わった場合はキャッシュをクリア (`make clean` で volume 削除) する。
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
// プロセス内で同じファイルへの再アクセス時に readdir/stat を省ける。
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

// キャッシュ本体 (ローカル SSD) の stat から ETag を作る。
// ローカルなので stat は常に成功する。
function etagOf(path: string): string {
  try {
    const st = statSync(path);
    return `"${st.size}-${Math.floor(st.mtimeMs)}"`;
  } catch {
    return '"cache"';
  }
}

/**
 * 既存キャッシュのパスを返す (無ければ null)。
 * - 新形式: `<sha1(relPath)>`
 * - 旧形式: `<sha1(relPath)>_<size>_<mtime>` も流用 (以前のキャッシュを捨てない)
 */
function findCache(relPath: string): string | null {
  const key = keyFor(relPath);
  const direct = join(CACHE_DIR, key);
  if (existsSync(direct)) return direct;
  try {
    const prefix = key + '_';
    const cands = readdirSync(CACHE_DIR)
      .filter((n) => n.startsWith(prefix) && !n.endsWith('.tmp'))
      .sort();
    if (cands.length > 0) return join(CACHE_DIR, cands[cands.length - 1]);
  } catch {
    /* CACHE_DIR が無い等 */
  }
  return null;
}

export interface CachedResult {
  /** 配信すべきバイト列 */
  body: Buffer;
  /** ETag (cache 本体の size-mtimeMs) */
  etag: string;
  /** クライアントの If-None-Match と一致したか (= 304 を返してよい) */
  notModified: boolean;
}

/**
 * relPath のファイルを「キャッシュ優先」で取得する。
 *
 * 1. キャッシュがあれば、それを読んで返す (元ファイル= Drive に触れない)
 * 2. キャッシュが無ければ、実ファイル (srcPath) を 1 回だけ読む
 *    - 成功: キャッシュへ atomic 書き込み → 返す
 *    - 失敗: null (= 呼び出し側で 404。キャッシュも無いので配信不能)
 */
export function serveCached(
  relPath: string,
  srcPath: string,
  ifNoneMatch: string | null,
): CachedResult | null {
  // --- 1) キャッシュがあればキャッシュを読む ---

  // 1a) メモリ index (readdir すら省く最速パス)
  const mem = memIndex.get(relPath);
  if (mem && existsSync(mem.cachePath)) {
    if (ifNoneMatch && ifNoneMatch === mem.etag) {
      return { body: Buffer.alloc(0), etag: mem.etag, notModified: true };
    }
    try {
      return {
        body: readFileSync(mem.cachePath),
        etag: mem.etag,
        notModified: false,
      };
    } catch {
      /* キャッシュ破損 → ディスク走査 / 実ファイルへ */
    }
  }

  // 1b) ディスク上のキャッシュ
  const cached = findCache(relPath);
  if (cached) {
    const etag = etagOf(cached);
    if (ifNoneMatch && ifNoneMatch === etag) {
      memIndex.set(relPath, { etag, cachePath: cached });
      return { body: Buffer.alloc(0), etag, notModified: true };
    }
    try {
      const body = readFileSync(cached);
      memIndex.set(relPath, { etag, cachePath: cached });
      return { body, etag, notModified: false };
    } catch {
      /* キャッシュ破損 → 実ファイル読みにフォールバック */
    }
  }

  // --- 2) キャッシュが無い → 実ファイルを読む ---
  let body: Buffer;
  try {
    body = readFileSync(srcPath);
  } catch {
    // Drive FUSE EDEADLK / 未 materialise 等。キャッシュも無いので配信不能。
    return null;
  }

  // キャッシュへ atomic 書き込み (失敗しても配信は継続)
  ensureCacheDir();
  const cachePath = join(CACHE_DIR, keyFor(relPath));
  let etag = `"${body.length}-0"`;
  try {
    const tmp = cachePath + '.tmp';
    writeFileSync(tmp, body);
    renameSync(tmp, cachePath);
    etag = etagOf(cachePath);
    memIndex.set(relPath, { etag, cachePath });
  } catch {
    /* cache 書けなくても OK (今回分は実ファイルの body を返す) */
  }

  return { body, etag, notModified: false };
}
