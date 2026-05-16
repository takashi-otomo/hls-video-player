# 03. フェーズ別計画とタイムライン

## 3.1 全体タイムライン

```
Week 1    Week 2     Week 3     Week 4      Week 5
│         │          │          │           │
├─MVP─────┤          │          │           │  Phase 1: Grid だけ動く
│         │          │          │           │
│         ├─Phase 2──┤          │           │  TS管理 / 変換UI / WebSocket
│         │          │          │           │
│         │          ├─Phase 3──┤           │  Polish / PWA / 性能調整
│         │          │          │           │
│         │          │          ├─Rollout───┤  並行運用 → 旧 Python 非推奨
```

## 3.2 Phase 0: Docker 環境準備 (Week 1, Day 1 午前)

**所要**: 半日

### タスク
- [ ] Docker Desktop の File Sharing に Drive パスを追加
- [ ] VirtIOFS を有効化
- [ ] `.env` と `.env.example` を作成
- [ ] `.gitignore` に `.env` `gui-web/node_modules/` を追加
- [ ] `docker/` ディレクトリと `docker-compose.yml` 雛形を作成
- [ ] `.dockerignore` を作成

### 完了条件
- `docker compose -f docker/docker-compose.yml config` がエラーなしで通る
- `docker run --rm hello-world` が動く

## 3.3 Phase 1 (MVP): グリッドビュー (Week 1, Day 1 午後 〜 Day 7)

**所要**: 5-7 営業日

### スコープ
- ライブラリ動画一覧 (グリッド表示)
- サムネ表示 + マウスホバーで slideshow
- お気に入りトグル
- クリックでプレイヤーへ遷移
- プレイヤーページ (Video.js + HLS.js)
- 動画長表示
- 文字列フィルタ / お気に入りフィルタ

### 含まれない (Phase 2 以降)
- TS結合管理タブ
- 変換実行 UI
- WebSocket ログ streaming
- index.md 編集 UI
- PWA インストール

### 完了条件
- Docker compose up で http://localhost:7860 に Grid 表示
- 既存 1290 件のライブラリで動作確認
- お気に入りが Python 版 `ts-merge --gui` と共有される
- プレイヤーで再生できる

詳細は [04-mvp-week1.md](04-mvp-week1.md)

## 3.4 Phase 2: TS結合管理 + 変換 UI (Week 2-3)

**所要**: 8-10 営業日

### スコープ
- **TS結合管理ビュー** (旧 Tkinter Tab 1 相当)
  - ファイル一覧テーブル (パート / MP4 / TS 状態)
  - index.md 追加・削除 UI
  - チェックボックス選択
  - 「TSパート削除」「indexから削除」操作
  - Colab コマンドコピー
- **変換実行 UI**
  - 「HLS 変換」ボタン → converter コンテナで `hls-convert` 実行
  - WebSocket でログを streaming 表示
  - 進捗バー (ファイル単位)
  - 完了通知
- **TS 結合実行 UI**
  - 「TS結合」ボタン → converter で `ts-merge` 実行
  - ログ streaming
- **再スキャンの自動化** (ファイル変更検知)

詳細は [07-python-bridge.md](07-python-bridge.md) (job queue 設計)

### 完了条件
- 旧 Tkinter GUI の機能をすべてカバー
- HLS 変換 / TS 結合がブラウザから実行できる

## 3.5 Phase 3: Polish + PWA (Week 4)

**所要**: 5 営業日

### スコープ
- **PWA 対応**
  - manifest.webmanifest 作成
  - アイコン (192x192, 512x512) 作成
  - Service Worker (任意、オフライン用)
  - インストールプロモートバナー
- **キーボードショートカット**
  - `←` / `→` で前後の動画
  - `F` でお気に入りトグル
  - `/` でフィルタ欄にフォーカス
  - `?` でショートカット一覧
- **UI 改善**
  - ダークモード調整
  - アクセシビリティ (aria-label, focus 表示)
  - レスポンシブ (スマホで /play 代替に使える)
- **エラーハンドリング**
  - 接続切れ時の再接続
  - 変換失敗時の retry UI
- **パフォーマンス最適化**
  - 仮想スクロールのチューニング
  - サムネ画像の遅延ロード
  - HTTP/2 設定確認

### 完了条件
- ブラウザの「インストール」ボタンで PWA 化できる
- すべての主要操作にキーボードショートカット
- Lighthouse PWA スコア 90+

## 3.6 Phase 4: Rollout (Week 5)

**所要**: 5 営業日

### スコープ
- **並行運用テスト**
  - Python `ts-merge --gui` と Docker 版を同時使用
  - お気に入り、変換出力の整合性確認
- **ドキュメント**
  - README に Docker 版の起動方法を追記
  - 旧 Tkinter の deprecation 告知
  - トラブルシューティングガイド
- **配布準備**
  - Docker イメージを GHCR (GitHub Container Registry) に push (任意)
  - `docker compose pull` でユーザーが取得できるように
- **最終受入テスト**
  - 全機能を Python 版と比較
  - パフォーマンスベンチ
  - 1280 件のフォルダで負荷テスト

### 完了条件
- Docker 版が Python 版を完全カバー
- ドキュメント完備
- 配布可能な状態

## 3.7 Phase 5 (将来): 旧 GUI の deprecate (Week 6+)

- README で「Docker 版を推奨」と明示
- `ts-merge --gui` 起動時に「Docker 版への移行案内」を表示
- 数週間〜数ヶ月後、Python GUI コード (`hls_video/ts_merge/gui.py`) を削除
- CLI (`hls-convert` / `ts-merge` の結合機能) は引き続き温存

## 3.8 マイルストーン一覧

| マイルストーン | 期限 | 検証方法 |
|---|---|---|
| **M0**: Docker 環境準備完了 | Week 1 Day 1 | `docker compose config` が通る |
| **M1**: API サーバ単体動作 | Week 1 Day 3 | `curl /api/videos` で 1290 件 JSON が返る |
| **M2**: Svelte SPA で Grid 表示 | Week 1 Day 5 | ブラウザでサムネ一覧が見える |
| **M3**: MVP 完成 (お気に入り + 再生) | Week 1 Day 7 | 全機能ブラウザで操作可 |
| **M4**: 変換 UI 動作 | Week 3 Day 3 | ブラウザから hls-convert 実行 + ログ表示 |
| **M5**: TS結合管理 UI 完成 | Week 3 Day 5 | 旧 Tkinter Tab1 を完全置換 |
| **M6**: PWA インストール可能 | Week 4 Day 3 | Chrome から「アプリをインストール」できる |
| **M7**: 並行運用受入 | Week 5 Day 5 | 旧 Python 版と Docker 版の機能対比表 100% 一致 |

## 3.9 リスク監視ポイント

各フェーズで以下を確認:

| Phase | リスク | 撤退基準 |
|---|---|---|
| MVP | グリッド描画が遅い (>2 秒) | Svelte 仮想スクロールの実装次第。Phase 1 終盤までに 500ms 切れなければ React に切替 |
| MVP | Drive FUSE で読み込みが遅い | Docker file sharing 設定。VirtIOFS でも遅ければ NFS 検討 |
| Phase 2 | converter ↔ gui の job queue 設計 | ファイル監視で破綻したら Redis / Bull など本格的なキューに移行 |
| Phase 2 | WebSocket の安定性 | Hono の WebSocket サポートが不十分なら SSE (Server-Sent Events) に切替 |

## 3.10 工数バッファ

各フェーズ +20% のバッファを見込む:

| フェーズ | 計画 | バッファ込み |
|---|---|---|
| Phase 0 | 0.5 日 | 1 日 |
| Phase 1 (MVP) | 7 日 | 8-9 日 |
| Phase 2 | 10 日 | 12 日 |
| Phase 3 | 5 日 | 6 日 |
| Phase 4 | 5 日 | 6 日 |
| **合計** | **27.5 日** | **約 5-6 週間** |
