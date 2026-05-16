# 変更履歴

形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に準拠。

## [Unreleased]

### Added — Docker Web 版 GUI (Bun + Svelte)
- **新 GUI**: Docker コンテナ内で動く Web アプリ (`make up` → http://localhost:7860)
  - ホスト依存は Docker Desktop のみ (Bun / Node / Python / ffmpeg はコンテナ内)
  - `gui` (Bun + Hono + Svelte) + `converter` (Python + ffmpeg) の 2 コンテナ構成
- **ライブラリビュー**: 仮想スクロールのグリッド、サムネ、ホバー slideshow、
  お気に入りトグル、お気に入り/文字列フィルタ、動画長・形式表示
- **プレイヤー**: Video.js + VHS で HLS 再生、シークバーサムネ preview、
  画質セレクタ、← 前 / 次 → ナビ、★ トグル、キーボード (←→ F Esc)、
  video.js は動的 import でコード分割
- **TS結合管理**: index.md 突合の状態一覧、状態フィルタ、URL 追加、
  index 削除、TSパート削除
- **変換実行**: HLS 変換 / TS 結合をブラウザから起動、WebSocket でログ
  リアルタイム streaming、ファイルベース job queue (`<lib>/.jobs/`)
- **PWA**: manifest + アイコン + Service Worker、ブラウザからインストール可
- **設定**: ライブラリパスを UI から変更・永続化
- `favorites.json` / `converted/hls-index.json` を旧 Python 版と共有 (並行運用可)
- `docs/migration-plan/` に設計計画書 11 本、`docs/troubleshoot.md` 追加
- `Makefile` で `--env-file .env` を隠蔽 (`make up/down/dev/logs/...`)

### Changed
- README を刷新: Docker Web 版を冒頭で推奨、CLI / レガシー Python 版を後段に整理
- `ts-merge --gui` (旧 Tkinter) は非推奨化 (起動時に Docker 版移行を案内)

## 旧 Python 版での主な変更 (要約)

### Added
- フォルダ走査モデル: `LIBRARY_ROOT` 配下を走査、`converted/{stem}/` に出力
- 5 ポイント (5/30/50/60/80%) サムネ + 3+2 合成 poster.png
- お気に入り機能 (`favorites.json`)
- `hls-convert` / `ts-merge` CLI (pipx)、`ts-merge --gui` Tkinter GUI
- グリッド再生ビュー (viewport ベース遅延描画)
- 変換済みインデックス (`hls-index.json`) で起動時判定を O(1) 化
- 中断検出 (`.converting` マーカー) + 自動再変換
- Colab notebook を GitHub clone ベースに刷新

### Fixed
- Drive FUSE の遅延・ECANCELED でハング/起動不能になる問題を多数修正
- macOS Tk のボタン色無視を Label ベースで回避
- pipx インストールで static/ が見つからない問題 (app パッケージ内へ移動)
- 背景スレッドからの root.after による shutdown race

### Performance
- GUI 起動時のインデックスロードを背景スレッド化
- グリッドを viewport ベース遅延描画 + サムネ load のスレッドプール化
- NVENC / filter_complex split / CUVID で変換を 10-30x 高速化
