# GUI 再構築計画 (Docker + Bun + Svelte)

現行 Python GUI (Tkinter / Gradio) を **Docker コンテナ内で動く Web アプリ**へ刷新するための計画書です。

## 採用方針 (承認済み)

| 項目 | 決定 |
|---|---|
| GUI 形態 | Docker コンテナ内で動く **Web アプリ** (ホスト無汚染) |
| Electron 採用 | **なし** (PWA インストールで代替) |
| コンテナ分離 | **(A) gui + converter の 2 コンテナ** |
| API ランタイム | **Bun** + Hono |
| フロントエンド | **Svelte** + Vite |
| 変換ツール | 既存 Python (`hls-convert` / `ts-merge`) を別コンテナで温存 |
| MVP 範囲 | **(A) グリッドビューだけ** (1 週間で動くもの) |
| 既存 Python GUI | **並行運用** → 新版安定後に deprecate |
| TS結合管理 UI | **グリッド完成後に Phase 2 で実装** |

## ドキュメント索引

| # | ファイル | 内容 |
|---|---|---|
| 01 | [architecture.md](01-architecture.md) | 全体アーキテクチャ・コンテナ分離・データフロー・技術選定 |
| 02 | [docker-setup.md](02-docker-setup.md) | Dockerfile / docker-compose / .env の具体例 |
| 03 | [phase-plan.md](03-phase-plan.md) | フェーズ別計画とタイムライン |
| 04 | [mvp-week1.md](04-mvp-week1.md) | MVP (Week 1) の日別実装手順 |
| 05 | [api-spec.md](05-api-spec.md) | Bun API エンドポイント仕様 |
| 06 | [frontend-design.md](06-frontend-design.md) | Svelte コンポーネント設計 |
| 07 | [python-bridge.md](07-python-bridge.md) | gui ↔ converter コンテナの連携設計 |
| 08 | [deployment-pwa.md](08-deployment-pwa.md) | 開発・配布・PWA 対応 |
| 09 | [risks-rollout.md](09-risks-rollout.md) | リスク・性能・並行運用・ロールアウト |
| 10 | [checklist.md](10-checklist.md) | 実装進捗チェックリスト |

## クイックスタート (実装開始時)

```bash
# 1. .env を作成 (動画フォルダのホストパス)
cd /Users/takashi/claude/hls-video-player
cat > .env <<'EOF'
LIBRARY_PATH=/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題
EOF

# 2. gui コンテナをビルド + 起動 (Phase 0-2 完了後)
docker compose -f docker/docker-compose.yml up gui --build

# 3. ブラウザで http://localhost:7860 を開く
```

## 完成イメージ

```
┌─────────────────────────────────────────────────────────────┐
│ Host (macOS)                                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Browser  ←──→  http://localhost:7860/  (PWA可)        │   │
│  └────────────────────────┬─────────────────────────────┘   │
│                           │                                  │
│  ┌────────────────────────▼─────────────────────────────┐   │
│  │ Docker Desktop                                        │   │
│  │  ┌──────────────────┐    ┌──────────────────┐         │   │
│  │  │ gui container    │    │ converter        │         │   │
│  │  │  Bun + Hono +    │←──→│  Python + ffmpeg │         │   │
│  │  │  Svelte SPA      │    │  hls-convert     │         │   │
│  │  └────────┬─────────┘    └──────┬───────────┘         │   │
│  │           └──────────┬───────────┘                    │   │
│  │                      ▼                                │   │
│  │            shared volume: /library                    │   │
│  └──────────────────────┼────────────────────────────────┘   │
│                          │                                   │
│                  /Users/takashi/.../myfans_見放題/            │
└─────────────────────────────────────────────────────────────┘
```

## 次のアクション

ドキュメント全体に目を通していただき、内容に問題なければ:

```
「Phase 0 (Docker 環境準備) から実装開始」
```

と指示してください。修正したい設計判断があれば該当ドキュメントを指摘してください。
