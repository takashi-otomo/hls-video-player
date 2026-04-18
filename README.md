# HLS Video Player

MP4 ソースを HLS（HTTP Live Streaming）に変換し、ブラウザ上で **アダプティブビットレート再生** と **シークバー上のサムネイルプレビュー** を実現する動画再生アプリです。

## 特徴

- **MP4 → HLS 変換**: FFmpeg で 720p / 480p / 360p / 240p の 4 段階 ABR ラダーを生成
  - `-sc_threshold 0`, `-g`/`-keyint_min` を固定してバリアント間でキーフレームを同期
  - VOD 向けに `hls_playlist_type=vod` を指定
- **マスタープレイリスト生成**: 解像度と帯域幅を記述した `master.m3u8` をサーバーサイドで自動生成
- **Video.js + VHS**: 追加プラグインなしでクロスブラウザに HLS を再生
- **シークバーサムネイルプレビュー**: FFmpeg の `tile` フィルタで単一画像を生成し、独自実装の tooltip（`background-position` で該当タイルをクリップ）でホバー／スクラブ時に表示
- **WebVTT**: `#xywh=X,Y,W,H` Media Fragments URI 付きの VTT ファイルを自動生成（外部プレイヤーと互換）
- **Express API**: `/api/videos`, `/hls/*`, `/sprites/*` を MIME 正しく配信
- **Docker Compose**: FFmpeg 同梱の Node 22 Alpine イメージで即起動

## プロジェクト構成

```
hls-video-player/
├── backend/
│   ├── src/
│   │   ├── app.js                    # Express アプリ本体
│   │   ├── index.js                  # 起動エントリポイント
│   │   ├── utils/
│   │   │   ├── ffmpegRunner.js       # ffmpeg / ffprobe 実行ラッパ
│   │   │   ├── hlsConverter.js       # MP4 → HLS 多解像度変換
│   │   │   ├── spriteGenerator.js    # スプライト + VTT 生成
│   │   │   ├── masterPlaylist.js     # master.m3u8 構築
│   │   │   ├── videoCatalog.js       # メディアディレクトリのスキャン
│   │   │   └── vttBuilder.js         # WebVTT 座標マッピング
│   │   └── __tests__/                # Jest ユニットテスト
│   ├── scripts/convert.js            # MP4 変換 CLI
│   ├── Dockerfile
│   └── package.json
├── frontend/
│   └── public/
│       ├── index.html                # ライブラリ一覧
│       ├── player.html               # Video.js プレイヤー
│       ├── library.js
│       ├── player.js
│       └── style.css
├── media/
│   ├── source/                       # 変換元 MP4 を置く
│   ├── hls/                          # 変換後 HLS 出力
│   └── sprites/                      # スプライト + VTT 出力
├── docker-compose.yml
└── README.md
```

## 開発ルール

プロジェクトルート CLAUDE.md のポリシーに従います:

- TDD: 機能実装前に Jest テストを追加 (`backend/src/__tests__/`)
- 1 コミット = 1 機能単位、commit 前に動作確認
- ブランチ: `feature/*` / `fix/*`

## クイックスタート（ローカル）

### 前提ツール
- Node.js 22+
- FFmpeg 6+ （`ffmpeg` / `ffprobe` が PATH にあること）

### 1. 依存インストールとテスト

```bash
cd backend
npm install
npm test
```

### 2. 動画を変換

`media/source/` に MP4 を配置して:

```bash
# 既定では <ファイル名>（英数字のみ）が id になる
npm run convert -- ../media/source/my-movie.mp4

# id を明示する場合
npm run convert -- ../media/source/my-movie.mp4 my-id
```

以下が生成されます:
- `media/hls/<id>/master.m3u8` と `240p/360p/480p/720p.m3u8` + `.ts` セグメント
- `media/sprites/<id>.jpg` — 10×10 タイル 160×90 のスプライト画像
- `media/sprites/<id>.vtt` — 各シーク時刻と `xywh` をマッピング
- `media/sprites/<id>.json` — プレイヤー初期化メタ情報

### 3. サーバー起動

```bash
npm start          # 本番起動
npm run dev        # watch モード
```

ブラウザで http://localhost:3000 を開くと一覧が表示されます。

## Docker で起動（推奨）

3 サービス構成:

| サービス | 役割 | ポート |
|---|---|---|
| **nginx** | 静的配信 (`/`, `/hls/*`, `/sprites/*`) + `/api/*` のリバースプロキシ | host: `8080` → container: `80` |
| **backend** | Express API (`/api/*`) | 内部のみ (`expose: 3000`) |
| **converter** | 一時起動の FFmpeg 変換タスク（`profiles: ["tools"]`） | — |

### 1. ビルド & 起動

```bash
docker compose up -d --build
```

http://localhost:8080 を開くとライブラリが表示されます。`docker-compose.override.yml` により開発時は `node --watch` でホットリロードします。本番モードで起動するには:

```bash
docker compose -f docker-compose.yml up -d
```

### 2. 動画を変換（コンテナ内 FFmpeg）

```bash
# media/source/your-video.mp4 を配置してから
docker compose run --rm converter /media/source/your-video.mp4 my-id
```

- ローカルに FFmpeg をインストール不要
- `media/` はバインドマウントなのでホスト側にも変換結果が残る
- `my-id` 省略時はファイル名から自動生成

### 3. 停止 / ログ

```bash
docker compose logs -f nginx backend
docker compose down
```

### アーキテクチャ図

```
              ┌──────────────────────┐
   :8080 ───▶│  nginx:1.27-alpine   │
              │  - / → static html   │
              │  - /hls/ → /media/hls│
              │  - /sprites/ → /media/sprites
              │  - /api/ → backend   │
              └───────┬──────────────┘
                      │ HTTP
                      ▼
              ┌──────────────────────┐
              │ backend (node:22)    │
              │ + ffmpeg (alpine)    │
              │ - /api/videos        │
              │ - healthcheck        │
              └──────────────────────┘

  converter（one-shot）───▶ ffmpeg → media/hls, media/sprites
```

### nginx の要点（`nginx/nginx.conf`）

- `types {}` ブロックで `.m3u8` → `application/vnd.apple.mpegurl`, `.ts` → `video/mp2t`, `.vtt` → `text/vtt` を明示
- `.ts` は `Cache-Control: public, max-age=31536000, immutable`、`.m3u8` は `no-cache`
- `Accept-Ranges: bytes` が自動で有効（Range リクエストで部分取得 → シーク高速化）
- 共通 CORS ヘッダで MSE / hls.js の cross-origin シナリオに対応

## 主要 API

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/health` | ヘルスチェック |
| GET | `/api/videos` | 変換済み動画カタログ |
| GET | `/api/videos/:id` | 個別動画メタ情報 |
| GET | `/api/sources` | `media/source/` 内の動画ファイル一覧（`converted`, `activeJobId` 付き） |
| POST | `/api/sources/:filename/convert` | 変換ジョブを起動（202、`{ jobId, videoId }` を返却） |
| GET | `/api/jobs` | ジョブ一覧（新しい順） |
| GET | `/api/jobs/:id` | ジョブ状態（`pending` / `running` / `completed` / `failed`） |
| GET | `/hls/:id/master.m3u8` | マスタープレイリスト |
| GET | `/hls/:id/:variant.m3u8` | 解像度別メディアプレイリスト |
| GET | `/hls/:id/:variant_NNN.ts` | セグメント |
| GET | `/sprites/:id.jpg` | スプライト画像 |
| GET | `/sprites/:id.vtt` | WebVTT |

MIME:
- `application/vnd.apple.mpegurl` (.m3u8)
- `video/mp2t` (.ts) — 長期キャッシュ
- `text/vtt` (.vtt)

## 技術的ポイント

### バリアント間キーフレーム同期

`backend/src/utils/hlsConverter.js` にて、各解像度ごとに以下を指定してバリアント間のキーフレーム位置を揃えています:

- `-sc_threshold 0`（シーンチェンジ検出を無効化）
- `-g` / `-keyint_min` を同一値（GOP サイズ固定）
- `-hls_time 4`（全バリアント共通）

これにより再生中の画質切り替えで映像のフリーズが発生しません。

### サムネイル座標計算

`backend/src/utils/vttBuilder.js` の `computeSpriteCoordinates`:

```
X = (i mod columns) × tileWidth
Y = ⌊i / columns⌋ × tileHeight
```

例: `columns=10`, `tileWidth=160`, `tileHeight=90` で i=12 のとき `(320, 90)` → VTT: `sprite.jpg#xywh=320,90,160,90`

### シークバープレビューの独自実装

外部プラグインに依存せず、`frontend/public/player.js` の `attachSeekbarPreview` 関数で実装しています:

- `mousemove` / `touchmove` でシークバー上の座標 → 時刻 (秒) を計算
- タイル index `i = floor(time / interval)` を算出し、`x = (i % columns) × tileWidth` / `y = floor(i / columns) × tileHeight`
- 1 枚のスプライト画像を `background-image` に固定、`background-position: -Xpx -Ypx` で該当タイルをクリップ表示
- マウント時に `new Image().src = url` でプリロード → 初回ホバーでもチラつきなし
- バックエンドが生成する `/sprites/<id>.json` のメタ情報 (`tileWidth`, `tileHeight`, `columns`, `interval`) を使用するため、タイルレイアウトを変えても JS 側は変更不要

## テスト

```bash
cd backend
npm test
```

- `spriteCoordinates.test.js` — 座標計算と VTT フォーマット
- `masterPlaylist.test.js` — マスタープレイリスト構築
- `videoCatalog.test.js` — ファイルシステム走査
- `app.test.js` — HTTP レイヤ（supertest）

## 本番運用での注意

- **CSP**: Video.js VHS は MSE 経由で Blob URL を生成するため、`media-src blob:` / `worker-src blob:` を CSP に含める
- **CDN キャッシュ**: `.ts` は immutable キャッシュ、`.m3u8` は `no-cache`
- **CMAF 移行**: 将来的に `-hls_segment_type fmp4` で fMP4 に移行すると HLS/DASH でセグメント共有が可能

## ライセンス

Private / Internal Use
