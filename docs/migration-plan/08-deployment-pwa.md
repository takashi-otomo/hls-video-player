# 08. 配布と PWA 対応

## 8.1 開発ワークフロー

### 初回セットアップ (1 回だけ)

```bash
cd /Users/takashi/claude/hls-video-player

# .env を作成
cat > .env <<'EOF'
LIBRARY_PATH=/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題
EOF

# Docker Desktop の File Sharing 設定 (手動 GUI 操作)
#   Settings → Resources → File Sharing → /Users/takashi/Library/CloudStorage を追加
#   Settings → General → "VirtIOFS" を有効化
```

### 日常の起動 / 停止

```bash
# 起動 (本番モード = ビルド済み SPA を配信)
docker compose -f docker/docker-compose.yml up -d

# 停止
docker compose -f docker/docker-compose.yml down

# ログ tail
docker compose -f docker/docker-compose.yml logs -f gui

# 再ビルド (コード変更後)
docker compose -f docker/docker-compose.yml up -d --build gui
```

### 開発モード (Hot Reload)

```bash
# Vite dev server を Docker で起動
docker compose -f docker/docker-compose.yml \
               -f docker/docker-compose.dev.yml \
               up

# ブラウザは http://localhost:5173 (Vite) で開く
# /api 等は Vite proxy で 7860 の Bun サーバへ転送
```

ホットリロードでファイル保存 → ブラウザ自動更新。

### コードフォーマット (任意)

ホスト無汚染を保つため Docker 経由:

```bash
docker run --rm -v $PWD/gui-web:/app -w /app oven/bun:1.1 \
  bun x prettier --write 'src/**/*.{svelte,ts,css}' 'server/**/*.ts'
```

## 8.2 ビルド・本番イメージ作成

### gui イメージ

```bash
docker compose -f docker/docker-compose.yml build gui
# → hls-video-player-gui:latest が作られる
```

イメージサイズ目安: **~150-200 MB** (multi-stage で SPA dist + Bun runtime のみ)

### converter イメージ

```bash
docker compose -f docker/docker-compose.yml build converter
# → hls-video-player-converter:latest
```

サイズ目安: **~500-700 MB** (Python + ffmpeg)

### イメージサイズ確認
```bash
docker images | grep hls-video-player
```

## 8.3 配布方法

### A) ローカル配布 (最初の段階で十分)

```bash
# A1. tar.gz で配布
docker save hls-video-player-gui:latest hls-video-player-converter:latest \
  | gzip > hls-video-player.tar.gz
# → 別マシンに転送
docker load < hls-video-player.tar.gz
# → docker-compose.yml と .env を渡せば動く
```

### B) GitHub Container Registry (Phase 4 以降、任意)

```bash
# B1. CI でビルド + push
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/takashi-otomo/hls-video-player-gui:v1.0 \
  -f docker/gui.Dockerfile --push .

# B2. ユーザー側
docker pull ghcr.io/takashi-otomo/hls-video-player-gui:v1.0
```

ただし private リポジトリの場合は GHCR の auth が必要。

### C) ソース配布 (推奨、初期段階)

```
ユーザー: git clone + docker compose up
所要時間: 初回 5 分 (build 含む)、以降の起動は数秒
```

README にこの手順を書いておけば十分。

## 8.4 PWA (Progressive Web App) 対応

ブラウザの「アプリをインストール」で Dock / タスクバーから起動可能にする。Electron なしで「ネイティブアプリ風」体験を実現。

### Step 1: manifest.webmanifest

```json
// gui-web/public/manifest.webmanifest
{
  "name": "HLS Video Library",
  "short_name": "HLS Library",
  "description": "Self-hosted HLS video library viewer",
  "start_url": "/",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#0a0c10",
  "theme_color": "#0a0c10",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

### Step 2: アイコン生成

Figma / Sketch / Affinity Designer で 512×512 PNG を 1 枚作る。それを 192×192 と maskable 版にリサイズ:

```bash
# ImageMagick で生成 (Docker から)
docker run --rm -v $PWD/gui-web/public:/work dpokidov/imagemagick \
  convert /work/icon-512.png -resize 192x192 /work/icon-192.png
```

### Step 3: index.html に link 追加

```html
<head>
  <link rel="manifest" href="/manifest.webmanifest" />
  <meta name="theme-color" content="#0a0c10" />
  <link rel="apple-touch-icon" href="/icon-192.png" />
</head>
```

### Step 4: Service Worker (任意、オフライン対応)

最小構成: ネットワーク優先、失敗時にキャッシュ:

```javascript
// gui-web/public/service-worker.js
const CACHE_VERSION = 'hls-v1';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_VERSION).then(cache => cache.addAll([
      '/',
      '/index.html',
      '/manifest.webmanifest',
      '/icon-192.png',
      '/icon-512.png',
    ]))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  // 動画 (/library/*) と API はキャッシュしない
  if (e.request.url.includes('/library/') || e.request.url.includes('/api/')) return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
```

`gui-web/src/main.ts` で登録:
```typescript
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js').catch(console.error);
}
```

### Step 5: ブラウザでインストール

- **Chrome / Edge**: URL バー右に「⊕ インストール」アイコンが出る → クリック
- **Safari**: 「ファイル」→「ドックに追加」(macOS 14 以降)
- **iOS Safari**: 共有→「ホーム画面に追加」

インストール後は専用ウィンドウで開かれ、ブラウザのアドレスバーが消えて Electron アプリのような見た目になる。

## 8.5 Auto Start (任意)

Docker Desktop の自動起動を有効化して、PC 起動時に gui コンテナが自動稼働するようにする。

```bash
# Docker Desktop の Settings → General → "Start Docker Desktop when you log in"
# → ON
```

docker-compose の `restart: unless-stopped` と組み合わせて、ログイン後すぐ http://localhost:7860 にアクセスできる状態に。

## 8.6 macOS Application Bundle (任意、Phase 4)

`/Applications/HLS Library.app` のようにダブルクリックで起動できる .app バンドルを作る。

`hls-library.app/Contents/MacOS/HLS Library` (実体は shell script):

```bash
#!/bin/bash
cd /Users/takashi/claude/hls-video-player
docker compose -f docker/docker-compose.yml up -d
sleep 2
open -a "Google Chrome" --new --args --app=http://localhost:7860/
```

これでドックの「HLS Library」アイコンクリックで起動する。

## 8.7 ホットフィックス (緊急対応)

本番運用中にバグが見つかった場合:

```bash
# 1. ソース修正 + commit + push
git commit -m "fix: ..." && git push

# 2. ホスト側で pull
git pull

# 3. リビルド + 再起動
docker compose -f docker/docker-compose.yml up -d --build gui
```

ダウンタイム ~10 秒。

## 8.8 ロールバック

特定バージョンに戻したい場合:

```bash
# 過去の commit へ戻す
git checkout <old-commit>
docker compose -f docker/docker-compose.yml up -d --build
```

または事前に `docker tag` でバージョンタグを打っておく:
```bash
docker tag hls-video-player-gui:latest hls-video-player-gui:v1.0
# 後でロールバック:
docker compose -f docker/docker-compose.yml down
# docker-compose.yml の image を v1.0 に変えるか、tag を latest に再付与
docker tag hls-video-player-gui:v1.0 hls-video-player-gui:latest
docker compose up -d
```

## 8.9 監視 / ログ

```bash
# ヘルスチェック
curl http://localhost:7860/api/health

# CPU/Memory 使用量
docker stats hls-gui hls-converter

# ログ (構造化されてれば jq で絞り込み)
docker compose logs gui | jq 'select(.level == "error")'
```

## 8.10 バックアップ

`favorites.json` `hls-index.json` `index.md` はそれぞれ Drive 上の Library フォルダ内にある。Drive 自体がバックアップなのでヒトの追加対応は不要。

Docker 側の永続化:
- `hls-config` named volume の中身は `settings.json` のみ → 喪失しても再設定で復旧可

## 8.11 アンインストール

```bash
# コンテナ + イメージ + ボリュームを完全削除
docker compose -f docker/docker-compose.yml down -v
docker rmi hls-video-player-gui hls-video-player-converter
docker volume rm hls-video-player_hls-config

# プロジェクトを git で消す
rm -rf /Users/takashi/claude/hls-video-player

# Drive 側のライブラリは触らない (動画 + favorites.json は Drive にある)
```

ホストには Docker Desktop 以外何も残らない。
