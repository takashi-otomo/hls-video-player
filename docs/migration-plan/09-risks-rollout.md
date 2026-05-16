# 09. リスク・性能・並行運用・ロールアウト

## 9.1 期待される性能改善

### 起動時間

| 操作 | 現 Tkinter | Docker Web App |
|---|---|---|
| GUI 表示まで | 2.5 秒 (Tk init + scan) | コンテナ起動済みなら **ブラウザで 0.5 秒** |
| グリッド 1280 件初描画 | viewport 内 ~30 widget 作成 で 400ms | DOM 仮想化で **< 200ms** |
| スクロール | place() 経由で再描画、~30fps | ブラウザネイティブ、**60fps** |
| サムネ初回ロード | Python 4 worker、~10ms/件 | ブラウザ HTTP/2 で **8 並列**、~5ms/件 |
| お気に入りトグル | 同期書込で ~100ms | 楽観的更新で **< 30ms** UI 反映 |
| プレイヤー切替 | iframe / webbrowser.open | Renderer 内ルーティング、**< 50ms** |

### メモリ使用量

| プロセス | 現 Python | Docker Web App |
|---|---|---|
| GUI 本体 | Tkinter 80MB + Python 50MB | Bun ~30MB |
| ブラウザ | (別) | Chrome タブ ~80MB |
| 合計 | ~130MB | ~110MB (PWA 化で同程度) |

### ベンチマーク戦略 (Phase 1 完了時に実施)

1. 1280 件の library で起動時間比較
2. グリッドスクロール 0 → 末尾まで → 0 を 5 周、fps 測定 (Chrome DevTools)
3. お気に入りトグル 100 回連続実行、応答時間分布
4. サムネ slideshow 同時 5 カードのフレーム落ち確認

合格基準: いずれも現 Python より同等以上。

## 9.2 リスクと対処

### 高優先度リスク

| # | リスク | 起こりやすさ | 影響 | 対処 |
|---|---|---|---|---|
| R1 | **Docker on macOS の I/O 遅延** | 中 | 大 | VirtIOFS 必須化、NFS マウントも検討、最悪 host network mode |
| R2 | **Drive FUSE が Docker から見えない** | 低 | 大 | File Sharing 設定の手順を README に明記。代替: rsync で手元 SSD に同期 |
| R3 | **Bun のメモリリーク / クラッシュ** | 低 | 中 | restart: unless-stopped で自動復帰、CI で長時間テスト |
| R4 | **Svelte 仮想スクロールが性能出ない** | 中 | 大 | 1280 件で 60fps 出なければ react-window 風の自前実装を強化、最悪 React に切替 |
| R5 | **Hono WebSocket の安定性** | 中 | 中 | 不安定なら SSE (Server-Sent Events) に切替、片方向通信なら十分 |
| R6 | **既存 favorites.json が壊れる** | 低 | 大 | atomic rename + バックアップ、Python 版 / Docker 版で同時書き込み回避 |
| R7 | **Drive FUSE 同期中の ECANCELED** | 中 | 中 | catch して空扱い (Python 版で既に実装、TS でも同じ対応) |

### 中優先度リスク

| # | リスク | 対処 |
|---|---|---|
| R8 | Docker Desktop ライセンス変更 | 個人用途は無料なので問題なし。商用なら OrbStack / colima 検討 |
| R9 | ポート 7860 競合 | docker-compose.yml で PORT を環境変数化、.env で変更可 |
| R10 | プレイヤーで HLS 再生できないブラウザ | Video.js + VHS で iOS Safari もカバー、最悪 hls.js を併用 |
| R11 | converter コンテナがビルド失敗 | Python の依存固定 (`requirements-lock.txt`)、CI でビルド検証 |

### 低優先度 (後で対処可)

- PWA Service Worker のバージョン管理
- 多言語対応 (現在日本語のみ)
- ダークモード以外のテーマ

## 9.3 既存 Python 版との並行運用

### 共存可能性

| 共有資源 | 共存可? | 注意点 |
|---|---|---|
| `LIBRARY_ROOT/converted/` | ✓ | 両方読み取り専用なので問題なし |
| `LIBRARY_ROOT/favorites.json` | ✓ | atomic rename 採用なので race condition なし |
| `LIBRARY_ROOT/converted/hls-index.json` | ✓ | 同上 |
| `LIBRARY_ROOT/index.md` | ⚠ | 同時編集はしないこと |
| `LIBRARY_ROOT/.jobs/` (Phase 2) | ✓ | Docker 版のみが書く |
| HTTP ポート 7860 | ✗ | Python `app.main` を使うなら **別ポートに変更** |

### 並行運用フェーズ (Week 5 ~)

```
朝の作業フロー:
1. ts-merge --gui ... を起動 (旧 Python)        ← TS パート管理に使う (Tab 1 機能用)
2. docker compose up -d                          ← Docker Web 版を起動
3. ブラウザで http://localhost:7860 を開く       ← 再生・グリッド閲覧は Web 版
4. ★ お気に入りはどちらからでも操作可能
5. 終了時: docker compose down + ts-merge GUI 閉じる
```

### お気に入り同期検証

並行運用テスト項目:
- [ ] Python 版で ★ON → Docker 版で「↻ 更新」して反映確認
- [ ] Docker 版で ★ON → Python 版でタブ切替時に最新を読み直す
- [ ] 両方から連続 100 回 ★ トグル → favorites.json が破損していない

## 9.4 ロールアウト計画 (Week 5)

### Day 1-2: 受入テスト
- [ ] 全機能を Python 版と機能対比表に照合
- [ ] パフォーマンスベンチ (上記基準を満たすか)
- [ ] エラーケース (Drive 切断、index.md 不在、converted/ 空 等) の挙動

### Day 3-4: ドキュメント整備
- [ ] README.md の冒頭に「Docker Web 版を推奨」と追記
- [ ] `colab_launch.ipynb` には変更を入れない (Colab は Python 版のまま)
- [ ] トラブルシューティング集を `docs/troubleshoot.md` に書く

### Day 5: 本番運用開始
- [ ] 自分の常用環境で `docker compose up -d` を default にする
- [ ] PWA インストールしてドック登録
- [ ] 1 週間使ってバグや使い勝手の問題を収集

### Week 6+: deprecation 告知
- [ ] `ts-merge --gui` 起動時に「⚠ 旧版です。Docker 版への移行を推奨」を表示
- [ ] 既存 Tkinter コード (`hls_video/ts_merge/gui.py`) は 1 ヶ月後に削除
- [ ] `hls-convert` / `ts-merge` の CLI は引き続き温存 (converter コンテナで使用)

## 9.5 撤退判断ライン

途中で「やはり Python 継続が良い」となるシナリオと、その判定基準:

| Phase | 判定タイミング | 撤退基準 |
|---|---|---|
| Phase 0 | 環境構築完了 | Docker on macOS の I/O が許容不能 (10x 遅延) なら中止 |
| Phase 1 MVP | Day 5 | グリッド描画が 1 秒以上、または ★ トグルが 200ms 以上ならフレームワーク見直し |
| Phase 1 MVP | Day 7 | 1280 件で動作不安定なら React + react-window に切替 |
| Phase 2 | Day 5 | converter ↔ gui の通信が安定しないなら HTTP RPC に切替 |
| Phase 3 | 完了時 | Python 版より明確に優れていない場合は **deprecation を保留** |

## 9.6 性能チューニングのヒント

### Bun サーバ
- `Bun.file(path).stream()` で zero-copy 配信
- Hono の `compress` middleware は HLS にかけない (既に小さい)
- `cache-control: public, max-age=...` を `.ts` セグメントに必ず付ける

### Svelte
- `{#each items as item (item.id)}` で keyed each → 再描画最小化
- Card.svelte の `$:` reactive は最小限に
- `<svelte:options immutable={true} />` で props 同一性比較に切替

### Docker
- BuildKit cache を使う: `DOCKER_BUILDKIT=1 docker compose build`
- Layer order: 変わりにくいもの (依存 install) を先、ソースを後
- `.dockerignore` で `node_modules` `dist` を除外

### macOS 固有
- Activity Monitor で `com.docker.virtio*` の CPU を監視
- Drive FUSE 経由の読み込みが遅い時は `mdutil -d` で Spotlight indexing を切る (動画フォルダのみ)

## 9.7 セキュリティ

### 想定脅威モデル
- ローカルマシンのみで稼働、外部公開しない前提
- 同一 LAN 内の他デバイスからアクセスする可能性は低い

### 対策
- API は **認証なし** (localhost 限定)
- ファイル配信 (`/library/*`) は `..` パストラバーサル防止
- Docker Desktop の File Sharing で必要最小限のパスのみ公開
- もし将来 LAN 内に公開するなら:
  - HTTPS 化 (Caddy / Nginx reverse proxy)
  - Basic Auth 追加
  - or VPN 内に限定

### 機密情報の取り扱い
- `.env` の `LIBRARY_PATH` には個人情報 (アカウント名等) を含むので gitignore
- favorites.json も同様だが、library フォルダ内に置くので Drive のアクセス制御に従う

## 9.8 ライセンス

- 本プロジェクト: 元のライセンスを継承 (README で確認)
- 使用ライブラリ:
  - Bun: MIT
  - Hono: MIT
  - Svelte: MIT
  - Vite: MIT
  - Video.js: Apache 2.0

すべて商用利用可。

## 9.9 アクセシビリティ

Phase 3 で対応:
- すべてのインタラクティブ要素に `aria-label`
- フォーカスリングを明示 (キーボード操作可)
- 動画タイトルのコントラスト確保
- スクリーンリーダー対応 (`role="grid"` 等)

## 9.10 国際化 (将来)

現状日本語のみ。将来必要なら `svelte-i18n` で:
- `src/locales/ja.json` / `src/locales/en.json`
- 動的にロード

Phase 3 範囲外。
