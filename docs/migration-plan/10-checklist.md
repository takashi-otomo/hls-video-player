# 10. 実装進捗チェックリスト

各 Phase のタスクを順に消化していくためのチェックリスト。

---

## Phase 0: Docker 環境準備 (0.5 日)

### ホスト側準備
- [ ] Docker Desktop が起動している
- [ ] Docker Desktop の Settings → Resources → File sharing に Drive パスを追加
- [ ] Docker Desktop の Settings → General → "VirtioFS" を有効化
- [ ] `docker info` で正常動作確認

### プロジェクト初期化
- [ ] `.env` を作成 (`LIBRARY_PATH=...`)
- [ ] `.env.example` を作成 (commit する)
- [ ] `.gitignore` に `/.env`, `gui-web/node_modules/`, `gui-web/dist/` を追加
- [ ] `.dockerignore` を作成
- [ ] `docker/` ディレクトリ作成
- [ ] `docker/gui.Dockerfile` を [02-docker-setup.md](02-docker-setup.md) から写経
- [ ] `docker/converter.Dockerfile` を同上
- [ ] `docker/docker-compose.yml` を同上
- [ ] `docker/docker-compose.dev.yml` (任意、Phase 1 で必要なら作る)

### 検証
- [ ] `docker compose -f docker/docker-compose.yml config` がエラーなし
- [ ] `docker run --rm hello-world` が動く

**完了条件**: `docker compose config` でサービス定義がパースされる

---

## Phase 1 (MVP): グリッドビュー (5-7 日)

### Day 1 — スキャフォールド

- [ ] `gui-web/` ディレクトリ作成
- [ ] Docker 経由で `bun init` 実行
- [ ] 依存追加: `hono`, `vite`, `@sveltejs/vite-plugin-svelte`, `svelte`, `typescript`, `svelte-check`, `@tsconfig/svelte`, `@types/node`, `svelte-spa-router`, `video.js`
- [ ] `gui-web/package.json` のスクリプト定義
- [ ] `gui-web/vite.config.ts` 作成
- [ ] `gui-web/tsconfig.json` 作成
- [ ] `gui-web/index.html` 作成

### Day 2-3 — Bun API サーバ

- [ ] `gui-web/server/lib/settings.ts` 実装 (library_settings.py 相当)
- [ ] `gui-web/server/lib/favorites.ts` 実装
- [ ] `gui-web/server/lib/index-file.ts` 実装 (converted_index.py 相当)
- [ ] `gui-web/server/lib/catalog.ts` 実装 (library_catalog.py 相当)
- [ ] `gui-web/server/index.ts` 実装 (Hono 起動)
- [ ] `gui-web/server/routes/health.ts` (`GET /api/health`)
- [ ] `gui-web/server/routes/settings.ts` (`GET /api/settings`, `POST .../library_root`)
- [ ] `gui-web/server/routes/videos.ts` (`GET /api/videos`, `GET /api/videos/:id`)
- [ ] `gui-web/server/routes/favorites.ts` (`GET /api/favorites`, `POST /api/favorites/:id`)
- [ ] `gui-web/server/routes/library.ts` (`GET /library/*`)

#### Day 3 検証
- [ ] `curl http://localhost:7860/api/health` → 200
- [ ] `curl http://localhost:7860/api/videos` → 1290 件 JSON
- [ ] `curl http://localhost:7860/api/videos/<uuid>` → 単一動画 JSON
- [ ] `curl -X POST .../api/favorites/<uuid>` → トグル成功
- [ ] `curl -I http://localhost:7860/library/<uuid>/thumbs/poster.png` → 200 + image/png

### Day 4 — Svelte SPA 基盤

- [ ] `gui-web/src/main.ts`
- [ ] `gui-web/src/App.svelte`
- [ ] `gui-web/src/app.css`
- [ ] `gui-web/src/lib/api.ts`
- [ ] `gui-web/src/lib/stores.ts`
- [ ] `gui-web/src/lib/types.ts`
- [ ] `gui-web/src/routes/Settings.svelte`
- [ ] svelte-spa-router でルーティング設定
- [ ] `bun run dev` で http://localhost:5173 が開く

### Day 5 — グリッドビュー

- [ ] `gui-web/src/lib/VirtualGrid.svelte` 実装
- [ ] `gui-web/src/lib/Card.svelte` 実装
  - [ ] サムネ表示
  - [ ] ホバーで slideshow (poster → 5%/30%/50%/60%/80% → poster)
  - [ ] お気に入りトグル (楽観的更新)
  - [ ] 動画長表示
  - [ ] 形式チップ (MP4/H.264)
- [ ] `gui-web/src/lib/FilterBar.svelte` (お気に入りのみ + 文字列フィルタ)
- [ ] `gui-web/src/routes/Library.svelte`
- [ ] 1290 件でスクロール 60fps 確認

### Day 6 — プレイヤーページ

- [ ] `gui-web/src/lib/HlsPlayer.svelte` (Video.js wrapper)
- [ ] 既存 `app/static/playerFactory.js` のロジック移植 (seek-bar preview, quality selector)
- [ ] `gui-web/src/routes/Player.svelte` (ナビゲーション + ★ + キーボードショートカット)
- [ ] グリッドからプレイヤーへ遷移
- [ ] HLS で再生できる
- [ ] ← 前 / 次 → が動く
- [ ] F でお気に入りトグル

### Day 7 — 仕上げ + 検証

- [ ] エラーハンドリング (404, ネットワーク切れ)
- [ ] ローディング表示
- [ ] 本番ビルド: `bun run build`
- [ ] gui.Dockerfile で multi-stage ビルド成功
- [ ] `docker compose up -d gui` で http://localhost:7860 で操作可
- [ ] Python `ts-merge --gui` と並行運用テスト
  - [ ] 両方からお気に入り変更 → favorites.json が壊れない
  - [ ] 両方から converted/ を見られる
- [ ] 1290 件で総合動作確認

**完了条件**: M1〜M3 (API 動作 / Grid 表示 / MVP 完成) クリア

---

## Phase 2: TS結合管理 + 変換 UI (10 日)

### Day 1 — converter 実装
- [ ] `docker/converter-entry.py` を作成
- [ ] `docker compose up converter` で idle 待機できる
- [ ] 手動で `.jobs/test.json` を置いて検知 + 実行確認

### Day 2 — gui 側 job queue
- [ ] `gui-web/server/lib/job-queue.ts`
- [ ] `gui-web/server/routes/convert.ts`
  - [ ] `POST /api/convert/start`
  - [ ] `GET /api/convert/jobs/:id`

### Day 3 — TS結合管理 API
- [ ] `gui-web/server/lib/ts-status.ts` (scan_folder_with_index 相当)
- [ ] `GET /api/ts-status`
- [ ] `POST /api/index/add`
- [ ] `DELETE /api/index/:uuid`
- [ ] `DELETE /api/ts-parts/:uuid`

### Day 4-5 — WebSocket でログ streaming
- [ ] Hono WebSocket セットアップ
- [ ] `WS /api/convert/jobs/:id/logs`
- [ ] フロントエンドで購読 + 表示
- [ ] status 同送

### Day 6-7 — TS結合管理 UI
- [ ] `gui-web/src/routes/TsManage.svelte`
- [ ] `gui-web/src/lib/EntryTable.svelte` (チェックボックス、状態カラー)
- [ ] `gui-web/src/lib/AddUrlForm.svelte`
- [ ] フィルタ (状態別)

### Day 8 — 変換実行 UI
- [ ] `gui-web/src/lib/ConvertPanel.svelte` (HLS 変換 + TS 結合)
- [ ] ログ表示 (auto-scroll)
- [ ] 進捗バー (簡易)
- [ ] エラー時の retry

### Day 9 — 結合テスト
- [ ] サンプル動画で HLS 変換実行 → 完了 → grid に反映
- [ ] TS 結合実行 → MP4 化
- [ ] 既存 Python CLI と挙動比較

### Day 10 — UI 仕上げ
- [ ] レイアウト調整
- [ ] ボタンの活性/非活性ロジック
- [ ] エラーメッセージ

**完了条件**: M4, M5 クリア

---

## Phase 3: Polish + PWA (5 日)

### Day 1 — PWA 準備
- [ ] アイコンデザイン (512x512)
- [ ] manifest.webmanifest 作成
- [ ] icon-192.png / icon-512.png / icon-maskable-512.png 生成
- [ ] index.html に link 追加
- [ ] Chrome で「インストール」アイコンが出る

### Day 2 — Service Worker (任意)
- [ ] `public/service-worker.js` 作成
- [ ] `main.ts` で登録
- [ ] オフライン時のフォールバック動作確認

### Day 3 — キーボードショートカット
- [ ] `←` / `→` / `F` (プレイヤー、既に Phase 1 で対応)
- [ ] `/` でフィルタにフォーカス (グリッド)
- [ ] `?` でショートカット一覧
- [ ] `Esc` でモーダル / プレイヤー閉じる

### Day 4 — UI / アクセシビリティ
- [ ] focus ring 表示
- [ ] aria-label 追加
- [ ] スマホ表示 (レスポンシブ確認)
- [ ] Lighthouse Audit (PWA / Performance / Accessibility)

### Day 5 — エラーハンドリング + 性能調整
- [ ] WebSocket 切断時の自動再接続
- [ ] Drive FUSE のレスポンス遅延への対応
- [ ] 仮想スクロールのチューニング
- [ ] HTTP/2 確認

**完了条件**: M6 クリア (Lighthouse PWA 90+)

---

## Phase 4: Rollout (5 日)

### Day 1-2 — 受入テスト
- [ ] 機能対比表で Python 版との一致を確認
- [ ] パフォーマンスベンチを 9.1 節の基準でクリア
- [ ] エラーケースを 9.2 節のリストで網羅

### Day 3-4 — ドキュメント
- [ ] README.md に Docker 起動手順
- [ ] トラブルシューティング集
- [ ] スクリーンショット撮影
- [ ] CHANGELOG.md 更新

### Day 5 — 本番運用開始
- [ ] 常用環境を Docker 版に切り替え
- [ ] PWA インストール
- [ ] 旧 Tkinter 起動時の警告メッセージ追加

**完了条件**: M7 クリア (機能対比 100% 一致)

---

## 最終確認チェックリスト (リリース判定)

### 機能対比
- [ ] グリッドビュー: Tkinter Tab 2 / Web /play の機能を完全カバー
- [ ] TS結合管理: Tkinter Tab 1 の機能を完全カバー
- [ ] プレイヤー: 既存 player_embed.py の機能を完全カバー
- [ ] お気に入り: Python 版と双方向同期

### 性能
- [ ] 起動 < 1 秒
- [ ] グリッド初描画 < 200ms
- [ ] スクロール 60fps 維持
- [ ] サムネ slideshow スムーズ
- [ ] お気に入りトグル UI 反映 < 50ms

### 安定性
- [ ] 24 時間連続稼働で正常動作
- [ ] Docker 再起動後も自動復帰 (`restart: unless-stopped`)
- [ ] Drive FUSE 切断時にハングしない
- [ ] WebSocket 切断時に自動再接続

### ドキュメント
- [ ] README.md (起動方法)
- [ ] docs/troubleshoot.md
- [ ] docs/migration-plan/ (本ドキュメント)
- [ ] CHANGELOG.md

### セキュリティ
- [ ] `.env` が gitignore されている
- [ ] パストラバーサル防止
- [ ] 同梱の Python パッケージに既知脆弱性なし

---

## 「やらない」ことの記録

明示的にスコープ外:

- ❌ Electron 採用 (Docker と相性悪い)
- ❌ ネイティブインストーラ (.dmg / .exe)
- ❌ LAN 共有 / マルチユーザー
- ❌ 多言語対応 (将来検討)
- ❌ 動画変換そのものを Bun で書き直し (Python のまま)
- ❌ Colab notebook の改修 (Python 版のまま)

---

## 進捗トラッキング方法

このチェックリストを `docs/migration-plan/10-checklist.md` に置き、実装中は適宜 [x] でマーク + git commit する。

```bash
git commit -m "docs(plan): Phase 1 Day 5 完了 — グリッドビュー実装"
```

各フェーズ完了時に git tag を打つ:
```bash
git tag electron-bun-mvp     # MVP 完了
git tag electron-bun-phase2  # Phase 2 完了
```
