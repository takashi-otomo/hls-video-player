# 04. MVP (Week 1) 実装手順

グリッドビューを 7 営業日で完成させる詳細プラン。

## 4.1 ゴール

```
http://localhost:7860/ にアクセスすると:
✓ ライブラリの動画 1290 件がグリッド表示される
✓ サムネにマウスを乗せると poster→5%→30%→50%→60%→80%→poster がループ
✓ ★ ボタンでお気に入りトグル (favorites.json に永続化、Python GUI と共有)
✓ 動画長 (⏱ 0:45) と ファイル形式 (MP4/H.264) が見える
✓ ★お気に入りフィルタ、文字列フィルタが動く
✓ ▶ 再生 / カード本体クリック → /player/<id> へ遷移
✓ プレイヤーで HLS が再生できる
✓ プレイヤーで ← 前 / 次 → のナビゲーション
✓ プレイヤーから ★ 切替できる
```

## 4.2 Day 1: 環境準備とスキャフォールド

### 午前: Docker 環境
- [ ] Docker Desktop の File Sharing 設定 (Drive パス追加)
- [ ] VirtIOFS 有効化
- [ ] `.env` 作成、`.gitignore` 更新
- [ ] `docker/` ディレクトリ作成
- [ ] `gui.Dockerfile`、`converter.Dockerfile`、`docker-compose.yml` の雛形を [02-docker-setup.md](02-docker-setup.md) からコピー
- [ ] `.dockerignore` 作成

```bash
cd /Users/takashi/claude/hls-video-player

cat > .env <<'EOF'
LIBRARY_PATH=/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題
EOF

cat > .env.example <<'EOF'
LIBRARY_PATH=/path/to/your/library
EOF

echo "/.env" >> .gitignore
echo "gui-web/node_modules/" >> .gitignore
echo "gui-web/dist/" >> .gitignore
echo "gui-web/.svelte-kit/" >> .gitignore
```

### 午後: gui-web スキャフォールド

ホストに Bun を入れたくないので、**Docker 内で初期化**する:

```bash
mkdir -p gui-web/{src,server,public}

# Bun コンテナで init
docker run --rm -it \
  -v $PWD/gui-web:/app \
  -w /app \
  oven/bun:1.1 bash -c "
    bun init -y && \
    bun add hono && \
    bun add -d vite @sveltejs/vite-plugin-svelte svelte typescript svelte-check @types/node && \
    bun add -d @tsconfig/svelte
  "

# 確認
ls gui-web/  # package.json, bun.lockb, node_modules, ...
```

#### `gui-web/package.json` を編集 (script を追加)

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "server": "bun run server/index.ts",
    "check": "svelte-check --tsconfig ./tsconfig.json"
  }
}
```

#### `gui-web/vite.config.ts`

```typescript
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    proxy: {
      // dev 時は API リクエストを Bun サーバに転送
      '/api':    'http://localhost:7860',
      '/library':'http://localhost:7860',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
```

#### `gui-web/tsconfig.json`

```json
{
  "extends": "@tsconfig/svelte/tsconfig.json",
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "resolveJsonModule": true,
    "types": ["node", "svelte", "vite/client"]
  },
  "include": ["src/**/*", "server/**/*"]
}
```

#### `gui-web/index.html`

```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>HLS Video Library</title>
  <link rel="manifest" href="/manifest.webmanifest" />
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

### 完了条件
- `docker compose -f docker/docker-compose.yml config` が通る
- `gui-web/package.json` ができている

## 4.3 Day 2: Bun API サーバの実装 (前半)

### タスク
- [ ] `gui-web/server/lib/settings.ts` を作成
- [ ] `gui-web/server/lib/favorites.ts` を作成
- [ ] `gui-web/server/lib/index-file.ts` を作成 (converted_index 相当)
- [ ] `gui-web/server/lib/catalog.ts` を作成 (library_catalog 相当)
- [ ] `gui-web/server/index.ts` を作成 (Hono 起動)
- [ ] `gui-web/server/routes/health.ts` (`/api/health`)

API 仕様は [05-api-spec.md](05-api-spec.md)、TypeScript 移植の方針は同ドキュメントの「移植ガイド」参照。

### Day 2 終わりの動作確認

```bash
# Bun サーバを Docker で起動 (まだ SPA 抜き)
docker run --rm -p 7860:7860 \
  -v $PWD/gui-web:/app \
  -v "/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題:/library" \
  -e LIBRARY_ROOT=/library \
  -w /app \
  oven/bun:1.1 \
  bun run server/index.ts

# 別ターミナル
curl http://localhost:7860/api/health
# → {"ok":true}
```

## 4.4 Day 3: Bun API サーバの実装 (後半)

### タスク
- [ ] `gui-web/server/routes/videos.ts` (`/api/videos`、`/api/videos/:id`)
- [ ] `gui-web/server/routes/favorites.ts` (`/api/favorites`、`/api/favorites/:id`)
- [ ] `gui-web/server/routes/library.ts` (`/library/*` 動的配信)
- [ ] `gui-web/server/routes/settings.ts` (`/api/settings`、`/api/settings/library_root`)

### Day 3 終わりの動作確認

```bash
curl http://localhost:7860/api/videos | jq '. | length'
# → 1290

curl http://localhost:7860/api/videos/<some-uuid>
# → JSON with title, duration, thumbs, posterUrl, isFavorite

curl -X POST -H 'Content-Type: application/json' \
  -d '{"favorited":true}' \
  http://localhost:7860/api/favorites/<some-uuid>
# → {"id":"<uuid>","isFavorite":true}

curl -I http://localhost:7860/library/<some-stem>/thumbs/poster.png
# → HTTP/1.1 200 + image/png
```

## 4.5 Day 4: Svelte SPA 基盤

### タスク
- [ ] `gui-web/src/main.ts`、`gui-web/src/App.svelte`
- [ ] `gui-web/src/app.css` (グローバルスタイル、Tailwind 不要、CSS で十分)
- [ ] `gui-web/src/lib/api.ts` (fetch wrapper)
- [ ] `gui-web/src/lib/stores.ts` (Svelte ストア)
- [ ] ライブラリパス設定画面 `gui-web/src/routes/Settings.svelte`
- [ ] 簡易ルーター (Svelte なら `svelte-spa-router` か自前で十分)

### Day 4 終わりの動作確認

```bash
# Vite dev server を Docker で起動
docker compose -f docker/docker-compose.yml \
               -f docker/docker-compose.dev.yml up

# http://localhost:5173 でライブラリパス設定画面が見える
# 保存ボタンで /api/settings/library_root が叩かれて値が変わる
```

## 4.6 Day 5: グリッドビュー実装

### タスク
- [ ] `gui-web/src/routes/Library.svelte` (グリッドの shell)
- [ ] `gui-web/src/lib/Card.svelte` (カード)
- [ ] `gui-web/src/lib/VirtualGrid.svelte` (仮想スクロール)
- [ ] ホバースライドショーロジック
- [ ] ★ お気に入りトグル
- [ ] 動画長表示

### 設計のポイント
- 1280 件すべてに `<div>` を作るのは無謀 → 仮想スクロール必須
- `IntersectionObserver` で可視カードのみサムネ画像を `<img>` でロード
- ホバー中だけ 6 枚をプリフェッチ
- お気に入り変更は楽観的更新 (即座に UI 反映 → サーバ確定で同期)

詳細は [06-frontend-design.md](06-frontend-design.md)

### Day 5 終わりの動作確認
- ブラウザでグリッド 1290 件が表示される
- スクロールしてもカクつかない
- ホバーで slideshow
- ★ クリックで黄色塗りつぶし

## 4.7 Day 6: プレイヤーページ + ナビゲーション

### タスク
- [ ] `gui-web/src/routes/Player.svelte`
- [ ] `gui-web/src/lib/HlsPlayer.svelte` (Video.js wrapper)
- [ ] 既存 `app/static/playerFactory.js` のロジックを Svelte に移植
- [ ] トップバー: ← 前 / ★ / 次 → / ✕ 閉じる
- [ ] キーボードショートカット (← / → / F)
- [ ] お気に入りトグル (Card と同じ /api/favorites)

### 設計のポイント
- Video.js は npm パッケージで入れる: `bun add video.js`
- HLS.js は Video.js の VHS が内蔵
- サムネ seek プレビュー (シークバーホバーで近いタイムスタンプの thumb 表示) も移植

### Day 6 終わりの動作確認
- グリッドから動画を選択 → プレイヤー画面で再生
- ← / → でシーケンシャル移動
- F でお気に入り切替

## 4.8 Day 7: 仕上げと検証

### タスク
- [ ] エラーハンドリング (404 / ネットワーク切れ)
- [ ] ローディング表示 (スピナー)
- [ ] 全機能の動作確認
- [ ] 1290 件のフォルダで性能ベンチ
- [ ] Python `ts-merge --gui` と並行運用テスト
  - 両方からお気に入り変更 → favorites.json が破損しないこと
  - 両方で変換出力を見られること
- [ ] 本番ビルド (`bun run build`) で dist 生成
- [ ] 本番モード Docker compose で起動 → http://localhost:7860 で動作確認

### 受入テスト項目
- [ ] 起動から Grid 表示まで 1 秒以内
- [ ] スクロール 60fps 維持
- [ ] サムネ slideshow がスムーズ
- [ ] ★ トグルが Python GUI と同期
- [ ] プレイヤーで HLS 再生 + 画質切替できる
- [ ] フィルタが正しく動く
- [ ] 1290 件で固まらない

## 4.9 Week 1 完了時の状態

- Docker compose up 1 発でブラウザ閲覧可能な GUI
- 既存 Python GUI と機能・お気に入り状態を共有
- Phase 2 (TS結合管理 + 変換 UI) の足場が整っている

## 4.10 Week 1 で「やらない」こと

明示的に範囲外:

- ❌ TS結合管理タブ
- ❌ index.md の編集 UI
- ❌ HLS 変換実行 UI
- ❌ TS結合実行 UI
- ❌ WebSocket / ログ streaming
- ❌ PWA manifest / Service Worker
- ❌ converter コンテナの実装 (Dockerfile だけ作って実行は Phase 2)

これらは Phase 2 で対応。

## 4.11 トラブル時のエスケープハッチ

Week 1 が間に合わない場合の優先順位:

1. **絶対譲れない**: Grid + サムネ + 再生
2. **譲れる**: お気に入り (Phase 2 で実装)
3. **譲れる**: フィルタ (Phase 2 で実装)
4. **譲れる**: 動画長表示 (Phase 2 で実装)

最悪「Grid + サムネ + 再生」だけ Week 1 で動けば、Phase 2 で残りを補える。
