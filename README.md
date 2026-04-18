# HLS Video Player

MP4 ソースを HLS（HTTP Live Streaming）に変換し、ブラウザ上で **アダプティブビットレート再生** と **シークバー上のサムネイルプレビュー** を実現する動画再生アプリです。

## 特徴

- **MP4 → HLS 変換**: FFmpeg で 720p / 480p / 360p / 240p の 4 段階 ABR ラダーを生成
  - `-sc_threshold 0`, `-g`/`-keyint_min` を固定してバリアント間でキーフレームを同期
  - VOD 向けに `hls_playlist_type=vod` を指定
- **マスタープレイリスト生成**: 解像度と帯域幅を記述した `master.m3u8` をサーバーサイドで自動生成
- **Video.js + VHS**: 追加プラグインなしでクロスブラウザに HLS を再生
- **スプライトサムネイル**: FFmpeg の `tile` フィルタで単一画像を生成、`videojs-sprite-thumbnails` v2 で遅延読み込み
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

## Docker で起動

```bash
docker compose up --build
```

`media/` と `frontend/public/` はボリュームマウントされるため、ホストで変換した動画がそのまま配信されます。

## 主要 API

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/health` | ヘルスチェック |
| GET | `/api/videos` | 変換済み動画カタログ |
| GET | `/api/videos/:id` | 個別動画メタ情報 |
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

### 遅延読み込み

`videojs-sprite-thumbnails` v2.2 以降、スプライト画像は動画再生開始時ではなくユーザーがシークバーに触れた瞬間に初めてダウンロードされます。初期再生のネットワーク帯域を圧迫しません。

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
