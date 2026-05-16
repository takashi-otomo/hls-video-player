# 05. Bun API エンドポイント仕様

既存 Python (FastAPI) の API を **そのままのインタフェース** で TypeScript / Hono に移植する。クライアント側の playerFactory.js などをそのまま使い回せるようにするため。

## 5.1 エンドポイント一覧

| Method | Path | 説明 | Phase |
|---|---|---|---|
| GET | `/api/health` | ヘルスチェック | 0 |
| GET | `/api/settings` | 現在のライブラリパス | 1 |
| POST | `/api/settings/library_root` | ライブラリパス変更 | 1 |
| GET | `/api/videos` | 変換済み動画一覧 | 1 |
| GET | `/api/videos/:id` | 単一動画詳細 | 1 |
| GET | `/api/favorites` | お気に入り一覧 | 1 |
| POST | `/api/favorites/:id` | お気に入りトグル | 1 |
| GET | `/library/*` | HLS / サムネ / poster 配信 | 1 |
| GET | `/api/ts-status` | TS結合管理用ステータス | 2 |
| POST | `/api/index/add` | index.md に URL 追加 | 2 |
| DELETE | `/api/index/:uuid` | index.md から削除 | 2 |
| DELETE | `/api/ts-parts/:uuid` | TSパート削除 | 2 |
| POST | `/api/convert/start` | HLS 変換ジョブ投入 | 2 |
| GET | `/api/convert/jobs/:id` | ジョブ状態取得 | 2 |
| WS | `/api/convert/jobs/:id/logs` | ジョブログ streaming | 2 |
| GET | `/player/:id` | プレイヤー HTML (旧互換) | 1 |
| GET | `/play` | スマホ向けライブラリ HTML (旧互換) | 1 |

## 5.2 レスポンス形式の共通ルール

- すべて `Content-Type: application/json; charset=utf-8`
- エラー時: `{ "error": "<message>" }` を適切な HTTP status で
- 成功時: 該当オブジェクト or `{ "ok": true, ... }`
- 配列は `[...]` 直接 (`{ "items": [...] }` ではない)

## 5.3 GET /api/health

最小のヘルスチェック。

```http
GET /api/health
```

レスポンス (200):
```json
{ "ok": true, "library_root": "/library", "library_root_exists": true }
```

## 5.4 GET /api/settings

現在の設定状態。

```json
{
  "library_root": "/library",
  "exists": true
}
```

## 5.5 POST /api/settings/library_root

ライブラリパスを変更。

```http
POST /api/settings/library_root
Content-Type: application/json

{ "library_root": "/library/another" }
```

- バリデーション: 存在しないパスは 400
- 永続化: `HLS_SETTINGS_FILE` (=`/config/settings.json`) に書き込み

成功 (200):
```json
{ "library_root": "/library/another", "message": "OK: /library/another" }
```

## 5.6 GET /api/videos

変換済み動画一覧。 Python の `library_catalog.list_videos()` 相当。

レスポンス (200):
```json
[
  {
    "id": "df9e64f8-a74e-415f-b708-aa16e1857d78",
    "title": "df9e64f8-a74e-415f-b708-aa16e1857d78.mp4",
    "duration": 5661.0,
    "width": 1280,
    "height": 720,
    "container": "mp4",
    "codec": "h264",
    "formatLabel": "MP4 / H.264",
    "isFavorite": false,
    "masterUrl": "/library/df9e64f8.../hls/master.m3u8",
    "posterUrl": "/library/df9e64f8.../thumbs/poster.png",
    "thumbs": [
      { "percent": 5,  "url": "/library/df9e64f8.../thumbs/thumb_05.jpg" },
      { "percent": 30, "url": "/library/df9e64f8.../thumbs/thumb_30.jpg" },
      { "percent": 50, "url": "/library/df9e64f8.../thumbs/thumb_50.jpg" },
      { "percent": 60, "url": "/library/df9e64f8.../thumbs/thumb_60.jpg" },
      { "percent": 80, "url": "/library/df9e64f8.../thumbs/thumb_80.jpg" }
    ]
  }
]
```

### 実装方針 (TS)
1. `LIBRARY_ROOT/converted/hls-index.json` を読む (1 file read)
2. `LIBRARY_ROOT/converted/` を listdir して dir 一覧取得 (1 listdir)
3. 各 stem について `converted/<stem>/meta.json` を読んでメタ取得 (並列、有界キュー)
4. favorites.json を読んで `isFavorite` を埋める

**キャッシュ戦略**: メモリに `Map<stem, VideoMeta>` を保持、ファイル mtime が変わったら invalidate。

## 5.7 GET /api/videos/:id

単一動画の詳細。`/api/videos` の 1 要素と同じ形。404 で `{ "error": "not_found" }`。

## 5.8 GET /api/favorites

```json
{ "favorites": ["stem-1", "stem-2", "..."] }
```

## 5.9 POST /api/favorites/:id

お気に入りトグル。

```http
POST /api/favorites/<stem>
Content-Type: application/json

{ "favorited": true }    # 省略時はトグル
```

レスポンス (200):
```json
{ "id": "<stem>", "isFavorite": true }
```

ファイル: `LIBRARY_ROOT/favorites.json`
```json
{ "favorites": ["stem-1", "stem-2"] }
```

排他制御は単一プロセス内なので JS の async lock で十分。ファイル書き込みは atomic rename (write to `.tmp` → rename)。

## 5.10 GET /library/*

`LIBRARY_ROOT/converted/` 配下のファイルを動的に配信。

例:
```
GET /library/df9e64f8.../hls/master.m3u8
→ /library/converted/df9e64f8.../hls/master.m3u8 を返す
```

### MIME / Cache 設定
| 拡張子 | Content-Type | Cache-Control |
|---|---|---|
| `.m3u8` | `application/vnd.apple.mpegurl` | `no-cache` |
| `.ts` | `video/mp2t` | `public, max-age=31536000, immutable` |
| `.vtt` | `text/vtt` | (default) |
| `.png` | `image/png` | `public, max-age=86400` |
| `.jpg/.jpeg` | `image/jpeg` | `public, max-age=86400` |
| `.json` | `application/json` | (default) |

すべて `Access-Control-Allow-Origin: *` をつける。

### セキュリティ
- リクエストパスに `..` を含む → 400
- `LIBRARY_ROOT/converted/` の外を指す → 403
- ファイルが存在しない → 404

### 実装例 (Hono + Bun)
```typescript
import { Hono } from 'hono';
import { stat } from 'fs/promises';
import { join, normalize, sep } from 'path';
import { getLibraryRoot } from '../lib/settings';
import { getConvertedDirName } from '../lib/index-file';

export const library = new Hono();

library.get('/*', async (c) => {
  const url = new URL(c.req.url);
  const rel = decodeURIComponent(url.pathname.replace(/^\/library\//, ''));
  if (rel.split('/').includes('..')) {
    return c.json({ error: 'invalid path' }, 400);
  }
  const base = join(getLibraryRoot(), getConvertedDirName());
  const target = normalize(join(base, rel));
  if (!target.startsWith(base + sep)) {
    return c.json({ error: 'forbidden' }, 403);
  }
  try {
    const s = await stat(target);
    if (!s.isFile()) return c.json({ error: 'not_found' }, 404);
  } catch {
    return c.json({ error: 'not_found' }, 404);
  }
  const ext = target.slice(target.lastIndexOf('.'));
  const mime = MIME[ext] ?? 'application/octet-stream';
  const cache = CACHE[ext] ?? '';
  return new Response(Bun.file(target).stream(), {
    headers: {
      'Content-Type': mime,
      ...(cache && { 'Cache-Control': cache }),
      'Access-Control-Allow-Origin': '*',
    },
  });
});
```

## 5.11 GET /player/:id

プレイヤー HTML を返す。既存 Python `app/player_embed.py` の `player_page_html()` を **そのまま移植**:
- 同じ class 名、id 名、JS 構造を保つ → `playerFactory.js` がそのまま動く
- ★ お気に入り、← 前 / 次 → ボタンの JS ロジックも同じ

実装方針: Hono の `c.html()` でテンプレート文字列を返す。

```typescript
playerRouter.get('/:id', (c) => {
  const id = c.req.param('id');
  return c.html(buildPlayerHtml(id));   // 既存 player_page_html を TS 移植
});
```

## 5.12 GET /play

スマホ向けライブラリ。既存 `_PLAY_PAGE_HTML` の移植。Svelte 化はせず素の HTML+JS でよい (旧仕様維持)。

## 5.13 Phase 2: TS結合管理用 API

### GET /api/ts-status

旧 Tkinter Tab 1 のステータス収集を JSON で返す。

```json
{
  "folder": "/library",
  "scanned_at": "2026-05-16T10:00:00Z",
  "entries": [
    {
      "uuid": "df9e64f8-...",
      "url": "https://example.com/posts/df9e64f8-...",
      "status": "MP4済",
      "part_count": 0,
      "total_size": 1234567,
      "merged_mp4": { "exists": true, "size": 1234567 },
      "merged_ts":  { "exists": false, "size": 0 },
      "split_mp4_count": 0,
      "complete": true,
      "missing": []
    }
  ],
  "counts": {
    "mp4": 1297, "mp4_ts": 0, "ts": 0,
    "pending": 0, "incomplete": 0, "no_dl": 93
  }
}
```

実装: Python の `scan_folder_with_index()` のロジックを TS に翻訳。`index.md` のパースは正規表現で同じ。

### POST /api/index/add

```http
POST /api/index/add
Content-Type: application/json

{ "urls": ["https://example.com/posts/abc...", "..."] }
```

レスポンス:
```json
{ "ok": true, "added": 2, "skipped": 1, "invalid": 0 }
```

### DELETE /api/index/:uuid

`index.md` から該当 URL の行を削除。

### DELETE /api/ts-parts/:uuid

ファイルシステムから `<uuid>_*-N.ts` を削除。

### POST /api/convert/start

```http
POST /api/convert/start
Content-Type: application/json

{
  "type": "hls",         // "hls" or "ts-merge"
  "filter": "abc",       // 任意
  "force": false,
  "workers": 2
}
```

レスポンス:
```json
{ "ok": true, "job_id": "01J9..." }
```

実装: `LIBRARY_ROOT/.jobs/<job_id>.json` に job spec を書く → converter コンテナが picks up → 詳細は [07-python-bridge.md](07-python-bridge.md)

### GET /api/convert/jobs/:id

```json
{
  "id": "01J9...",
  "type": "hls",
  "status": "running",     // "queued" | "running" | "done" | "failed"
  "started_at": "2026-05-16T10:00:00Z",
  "finished_at": null,
  "progress": 0.42,
  "log_path": "/library/.jobs/01J9....log"
}
```

### WS /api/convert/jobs/:id/logs

WebSocket でログ行を push する。Hono の WebSocket サポートを使用。

```javascript
const ws = new WebSocket('ws://localhost:7860/api/convert/jobs/01J9.../logs');
ws.onmessage = (e) => {
  const { type, line, code } = JSON.parse(e.data);
  if (type === 'log') console.log(line);
  if (type === 'exit') console.log(`exit ${code}`);
};
```

サーバ側: `fs.watch(logPath)` で行追加を検出して送信。

## 5.14 TypeScript 移植ガイド

Python ロジックを TS に翻訳する際の対応表。

### library_settings.py → settings.ts

```typescript
// gui-web/server/lib/settings.ts
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { homedir } from 'os';

const SETTINGS_FILE = process.env.HLS_SETTINGS_FILE
  ?? join(homedir(), '.config', 'hls-video-player', 'settings.json');

let cached: { library_root?: string } | null = null;

function loadFile(): { library_root?: string } {
  if (cached) return cached;
  if (!existsSync(SETTINGS_FILE)) {
    cached = {};
    return cached;
  }
  try {
    cached = JSON.parse(readFileSync(SETTINGS_FILE, 'utf-8'));
  } catch {
    cached = {};
  }
  return cached!;
}

export function getLibraryRoot(): string {
  const data = loadFile();
  if (data.library_root) return data.library_root;
  return process.env.LIBRARY_ROOT ?? './library';
}

export function setLibraryRoot(p: string): string {
  mkdirSync(dirname(SETTINGS_FILE), { recursive: true });
  const tmp = SETTINGS_FILE + '.tmp';
  writeFileSync(tmp, JSON.stringify({ library_root: p }, null, 2));
  // atomic rename
  Bun.rename ? Bun.rename(tmp, SETTINGS_FILE) : require('fs').renameSync(tmp, SETTINGS_FILE);
  cached = null;
  return p;
}

export function validateLibraryRoot(p: string): { ok: boolean; message: string } {
  if (!p) return { ok: false, message: 'パスが空です' };
  if (!existsSync(p)) return { ok: false, message: `パスが存在しません: ${p}` };
  // 簡易: ディレクトリか否か
  try {
    if (!require('fs').statSync(p).isDirectory()) {
      return { ok: false, message: `ディレクトリではありません: ${p}` };
    }
  } catch {
    return { ok: false, message: `アクセスできません: ${p}` };
  }
  return { ok: true, message: `OK: ${p}` };
}
```

### favorites.py → favorites.ts

```typescript
// gui-web/server/lib/favorites.ts
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot } from './settings';

interface FavoritesFile { favorites?: string[] }

function favoritesPath(): string {
  return join(getLibraryRoot(), 'favorites.json');
}

export function loadFavorites(): Set<string> {
  const p = favoritesPath();
  if (!existsSync(p)) return new Set();
  try {
    const data: FavoritesFile = JSON.parse(readFileSync(p, 'utf-8'));
    return new Set(data.favorites ?? []);
  } catch {
    return new Set();
  }
}

export function saveFavorites(favs: Set<string>): void {
  const p = favoritesPath();
  const tmp = p + '.tmp';
  writeFileSync(tmp, JSON.stringify({
    favorites: Array.from(favs).sort(),
  }, null, 2));
  require('fs').renameSync(tmp, p);
}

export function toggleFavorite(id: string): boolean {
  const favs = loadFavorites();
  if (favs.has(id)) {
    favs.delete(id);
    saveFavorites(favs);
    return false;
  }
  favs.add(id);
  saveFavorites(favs);
  return true;
}

export function setFavorite(id: string, favorited: boolean): boolean {
  const favs = loadFavorites();
  if (favorited) favs.add(id); else favs.delete(id);
  saveFavorites(favs);
  return favorited;
}
```

### converted_index.py → index-file.ts

`hls-index.json` の読み込み / レガシー (`.hls-index.json` / `.index.json`) からのフォールバック。同じロジックを TS で書く (~80 行)。

### library_catalog.py → catalog.ts

`listVideos()` / `getVideo(stem)` の TS 実装。LRU キャッシュ + mtime ベース invalidation を入れて再読込を最小化。

## 5.15 エラーハンドリング指針

- ファイル I/O 失敗 (Drive FUSE の ECANCELED 等): catch して空配列 / 空オブジェクト返却 + log
- 不正なリクエスト: 400 + `{ "error": "..." }`
- 認証不要 (localhost 限定なので)
- レート制限不要 (単一クライアント)

## 5.16 ロギング

- 標準出力に JSON 1 行 / リクエスト (アクセスログ)
- Hono の logger middleware を使う:

```typescript
import { logger } from 'hono/logger';
app.use('*', logger());
```

- エラーは `console.error` で stack trace 込み
- Docker compose ログから即見られる: `docker compose logs -f gui`
