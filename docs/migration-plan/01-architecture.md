# 01. アーキテクチャと技術選定

## 1.1 全体構成

```
┌───────────────────────────────────────────────────────────────────┐
│ Host PC (macOS / Linux / Windows)                                 │
│                                                                   │
│  Web ブラウザ                                                      │
│  ←─── HTTP ───→  http://localhost:7860/                            │
│  - PWA インストール可 (Chrome / Edge)                              │
│  - Safari は標準ショートカット作成で同等                            │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ Docker Desktop                                              │ │
│  │                                                             │ │
│  │   internal network: hls-net                                 │ │
│  │   ┌──────────────────────┐    ┌──────────────────────────┐  │ │
│  │   │  container: gui      │    │  container: converter    │  │ │
│  │   │  image: gui-bun:1    │    │  image: converter-py:1   │  │ │
│  │   │                      │    │                          │  │ │
│  │   │  - Bun + Hono        │    │  - Python 3.12           │  │ │
│  │   │  - Svelte SPA (静的) │    │  - ffmpeg                │  │ │
│  │   │  - port 7860 expose  │    │  - hls-convert (CLI)     │  │ │
│  │   │                      │    │  - ts-merge   (CLI)      │  │ │
│  │   │  job queue 監視 ──→ │←───│  job queue 実行           │  │ │
│  │   │  (ファイル監視)      │    │  (poll loop)             │  │ │
│  │   └──────────┬───────────┘    └─────────┬────────────────┘  │ │
│  │              │  共有 volume mount       │                   │ │
│  │              ▼                          ▼                   │ │
│  │   ┌─────────────────────────────────────────────────┐       │ │
│  │   │  /library  (ホスト側 LIBRARY_PATH を bind mount) │       │ │
│  │   │   ├── *.mp4                                     │       │ │
│  │   │   ├── index.md                                  │       │ │
│  │   │   ├── favorites.json                            │       │ │
│  │   │   ├── .jobs/                  ← job queue       │       │ │
│  │   │   └── converted/                                │       │ │
│  │   │       ├── hls-index.json                        │       │ │
│  │   │       └── <stem>/{hls,thumbs,meta.json}         │       │ │
│  │   └─────────────────────────────────────────────────┘       │ │
│  └─────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
                                ▲
                          /Users/takashi/.../myfans_見放題/
                          (Google Drive FUSE mount)
```

## 1.2 コンテナ分離の役割

### gui コンテナ
- **責任**: HTTP API + 静的 SPA 配信
- **常時稼働**: ユーザーがアクセスしている間は常に立っている
- **資源**: ~50MB RAM、CPU 1 core 未満
- **読み書き**: メタデータ系 (favorites.json, hls-index.json) と静的アセット読み込み

### converter コンテナ
- **責任**: TS 結合 / HLS 変換 / サムネ生成
- **idle**: 通常は `tail -f /dev/null` で待機
- **起動契機**: gui が `/library/.jobs/<id>.json` を作る → converter が polling で検知して実行
- **資源**: 実行中は CPU 全コア、RAM 1-2GB (ffmpeg 次第)
- **完了時**: ログを `/library/.jobs/<id>.log` に書き、ステータスを更新

## 1.3 データフロー (再生)

```
1. Browser:  fetch /api/videos
2. gui:      LIBRARY_ROOT/converted/hls-index.json を読む
3. gui:      JSON で 1290 件のメタデータを返す
4. Browser:  グリッド描画、サムネ URL は /library/<stem>/thumbs/poster.png
5. Browser:  fetch /library/<stem>/thumbs/poster.png (gui が file streaming)
6. ユーザーがクリック → /player/<stem>
7. Browser:  Video.js が /library/<stem>/hls/master.m3u8 を読みに行く
8. gui:      HLS の m3u8 / ts を静的配信 (Cache-Control 含む)
```

## 1.4 データフロー (HLS 変換)

```
1. Browser:  POST /api/convert/start  (body: 任意のフィルタ)
2. gui:      /library/.jobs/<id>.json に job spec を書き込み
3. gui:      Browser に job ID を返す
4. Browser:  WebSocket で /api/convert/jobs/<id>/logs を購読
5. converter:  poll loop で /library/.jobs/<id>.json を検知
6. converter:  hls-convert を spawn、stdout を /library/.jobs/<id>.log に append
7. gui:      ログファイルを watch して WebSocket 経由で Browser に push
8. converter:  完了したら /library/.jobs/<id>.status = "done"
9. gui:      WebSocket でクライアントに完了を通知
```

詳細は [07-python-bridge.md](07-python-bridge.md) を参照。

## 1.5 技術選定の根拠

### Bun + Hono (API 側)
- **理由**:
  - 起動が速い (Node.js の 4 倍)
  - HTTP サーバが超高速 (Express の 3-5 倍)
  - TypeScript ネイティブ実行 (transpile 不要)
  - `Bun.file()` の streaming が極めて軽量
- **代替案との比較**:
  - Node.js + Express: 動くが Bun の方が単純に速い
  - Deno: 良い選択肢だが Bun の方がエコシステム充実
  - Python FastAPI 継続: 性能改善目的なら捨てるのが正解

### Svelte (フロントエンド)
- **理由**:
  - コンパイル時にランタイムを大幅削減 → バンドル小さい (~20KB vs React の ~140KB)
  - 学習コスト低 (HTML/CSS/JS をそのまま書ける)
  - リアクティビティが直感的 (`$:` 構文)
  - 仮想 DOM 不要 → 初描画が高速
- **代替案との比較**:
  - React: エコシステム最大だが学習コスト高
  - Vue: 中庸だが Svelte より重い
  - Vanilla JS: 規模が大きくなると破綻

### Docker Compose
- **理由**:
  - 2 コンテナの相互依存・network・volume を宣言的に管理
  - `up` 1 発で開発環境構築
  - macOS / Linux / Windows で同一動作
- **代替案との比較**:
  - 単一コンテナ: イメージ肥大 (~600MB)、関心分離できない
  - Kubernetes: 過剰スペック

## 1.6 ディレクトリ構造 (新規追加分)

```
hls-video-player/
├── app/, hls_video/             ← 既存 Python (温存)
├── docs/
│   └── migration-plan/          ← 本ドキュメント
├── docker/
│   ├── gui.Dockerfile           ← Bun + Svelte ビルド
│   ├── converter.Dockerfile     ← Python + ffmpeg
│   └── docker-compose.yml       ← 2 コンテナ構成
├── gui-web/                     ← 新 GUI ソース
│   ├── package.json
│   ├── bun.lockb
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── server/                  ← Bun サーバ (TypeScript)
│   │   ├── index.ts             ← エントリポイント
│   │   ├── routes/
│   │   │   ├── videos.ts        ← /api/videos
│   │   │   ├── favorites.ts     ← /api/favorites
│   │   │   ├── library.ts       ← /library/*
│   │   │   ├── settings.ts      ← /api/settings
│   │   │   └── convert.ts       ← /api/convert (Phase 2)
│   │   └── lib/
│   │       ├── catalog.ts       ← library_catalog 相当
│   │       ├── favorites.ts     ← favorites 相当
│   │       ├── settings.ts      ← library_settings 相当
│   │       ├── index-file.ts    ← converted_index 相当
│   │       └── job-queue.ts     ← ファイルベース job queue (Phase 2)
│   ├── src/                     ← Svelte SPA
│   │   ├── main.ts
│   │   ├── App.svelte
│   │   ├── routes/
│   │   │   ├── Library.svelte   ← グリッドビュー
│   │   │   ├── Player.svelte    ← 再生ページ
│   │   │   ├── Settings.svelte
│   │   │   └── TsManage.svelte  ← Phase 2
│   │   ├── lib/
│   │   │   ├── api.ts           ← fetch wrapper
│   │   │   ├── stores.ts        ← Svelte stores
│   │   │   ├── Card.svelte      ← グリッドカード
│   │   │   ├── VirtualGrid.svelte ← 仮想スクロール
│   │   │   └── HlsPlayer.svelte ← Video.js wrapper
│   │   └── app.css
│   ├── public/
│   │   ├── manifest.webmanifest ← PWA
│   │   ├── icon-192.png
│   │   ├── icon-512.png
│   │   └── service-worker.js    ← オフライン用 (任意)
│   └── .gitignore
├── .env                         ← LIBRARY_PATH (gitignore)
├── .env.example                 ← サンプル (commit する)
└── colab_launch.ipynb           ← 既存
```

## 1.7 既存資産の流用

新しく書き直すのは **GUI と API 層だけ**。以下は既存のものを利用:

| 既存 | 新側での扱い |
|---|---|
| `app/static/playerFactory.js` | `gui-web/src/lib/HlsPlayer.svelte` 内でそのまま読み込み |
| `hls_video/library_converter.py` | converter コンテナ内で実行 (Python のまま) |
| `hls_video/thumbnail_generator.py` | 同上 |
| `hls_video/ts_merge/merge.py` | 同上 |
| `hls_video/library_catalog.py` のロジック | TypeScript に翻訳 (~80 行) |
| `hls_video/favorites.py` のロジック | TypeScript に翻訳 (~40 行) |
| `hls_video/library_settings.py` のロジック | TypeScript に翻訳 (~30 行) |
| `hls_video/converted_index.py` のロジック | TypeScript に翻訳 (~100 行) |

Python の薄い読み取り系ロジック (~250 行) のみ TS に翻訳。重い変換処理は Python のまま。
