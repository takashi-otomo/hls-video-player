# 02. Docker 構成

## 2.1 ファイル一覧

| ファイル | 役割 |
|---|---|
| `docker/gui.Dockerfile` | Bun + Svelte SPA のビルド + サーブ |
| `docker/converter.Dockerfile` | Python + ffmpeg + hls-convert/ts-merge |
| `docker/docker-compose.yml` | 2 コンテナ + 共有 volume + network |
| `.env` | ホスト側ライブラリパス (gitignore) |
| `.env.example` | サンプル (commit) |

## 2.2 `docker/gui.Dockerfile`

マルチステージビルドで Svelte の dist を作ってから軽量ランタイムに差し込む。

```dockerfile
# syntax=docker/dockerfile:1.7

# === Stage 1: SPA をビルド ===
FROM oven/bun:1.1 AS builder

WORKDIR /app

# bun の lockfile を先に COPY して install をキャッシュ
COPY gui-web/package.json gui-web/bun.lockb ./
RUN bun install --frozen-lockfile

# ソース投入後にビルド
COPY gui-web/ ./
RUN bun run build

# === Stage 2: ランタイム (Bun サーバ + dist) ===
FROM oven/bun:1.1-slim AS runtime

WORKDIR /app

# サーバ実行に必要なものだけコピー
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/server ./server
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules

ENV LIBRARY_ROOT=/library
ENV PORT=7860
EXPOSE 7860

# 設定 dir (favorites.json 等の永続化先)
RUN mkdir -p /config
ENV HLS_SETTINGS_FILE=/config/settings.json

# health check
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:7860/api/health || exit 1

CMD ["bun", "run", "server/index.ts"]
```

**ポイント**:
- マルチステージで最終イメージサイズを ~150MB に抑える
- `bun.lockb` で依存ロック (再現可能ビルド)
- HEALTHCHECK で gui の死活監視 (docker compose 側で再起動連動)
- 設定ファイル (`settings.json`) は `/config/` に永続化 → docker volume で保持

## 2.3 `docker/converter.Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

# ffmpeg + git (pip install -e で必要) + curl (health check) を最小構成で
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pyproject.toml + ソースを投入して editable install
COPY pyproject.toml ./
COPY hls_video/ ./hls_video/
COPY app/ ./app/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .

ENV LIBRARY_ROOT=/library
# Docker on macOS では NVENC 使えないので CPU で
ENV FFMPEG_HWACCEL=cpu
ENV FFMPEG_PRESET=ultrafast
ENV FFMPEG_AUDIO_COPY=1
ENV FFMPEG_VARIANTS=720p,360p

# job queue poll loop を実行 (Phase 2)
# Phase 0/MVP では idle 待機だけ
COPY docker/converter-entry.py /usr/local/bin/converter-entry
RUN chmod +x /usr/local/bin/converter-entry

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["converter-entry"]
```

`docker/converter-entry.py` は Phase 2 で実装する job queue poller。Phase 0 / MVP では `tail -f /dev/null` 相当の sleep ループでも OK。

## 2.4 `docker/docker-compose.yml`

```yaml
# docker compose -f docker/docker-compose.yml up
version: "3.9"

name: hls-video-player

services:
  gui:
    build:
      context: ..
      dockerfile: docker/gui.Dockerfile
    container_name: hls-gui
    ports:
      - "7860:7860"
    volumes:
      # ホスト側のライブラリフォルダ
      - "${LIBRARY_PATH:?LIBRARY_PATH を .env で設定してください}:/library"
      # 設定の永続化 (favorites.json は library 内、ここは UI 設定だけ)
      - hls-config:/config
    environment:
      LIBRARY_ROOT: /library
      HLS_SETTINGS_FILE: /config/settings.json
      PORT: 7860
      NODE_ENV: production
    networks:
      - hls-net
    restart: unless-stopped
    depends_on:
      - converter

  converter:
    build:
      context: ..
      dockerfile: docker/converter.Dockerfile
    container_name: hls-converter
    volumes:
      - "${LIBRARY_PATH:?LIBRARY_PATH を .env で設定してください}:/library"
    environment:
      LIBRARY_ROOT: /library
      FFMPEG_HWACCEL: cpu
      FFMPEG_PRESET: ultrafast
      FFMPEG_AUDIO_COPY: "1"
      FFMPEG_VARIANTS: "720p,360p"
    networks:
      - hls-net
    restart: unless-stopped

networks:
  hls-net:
    driver: bridge

volumes:
  hls-config:
```

**特徴**:
- `LIBRARY_PATH` を `.env` から強制要求 (`:?` 構文)
- gui と converter は同じ `hls-net` で通信 (内部 DNS で `converter:7860` のような名前解決可)
- `hls-config` volume で UI 設定だけ永続化 (favorites.json は library 内)
- `restart: unless-stopped` で Docker Desktop 再起動後も自動復帰

## 2.5 `.env.example` (commit する)

```bash
# 動画フォルダの絶対パス (ホスト側)
# Google Drive on macOS の例:
LIBRARY_PATH=/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題

# (任意) ポート変更
# PORT=7860
```

## 2.6 `.env` (実際の値、gitignore)

```bash
LIBRARY_PATH=/Users/takashi/Library/CloudStorage/GoogleDrive-tekinananika@gmail.com/マイドライブ/置き場/myfans_見放題
```

`.gitignore` に `/.env` を追加。

## 2.7 macOS の Drive FUSE マウント注意点

Docker Desktop の File Sharing 設定で `/Users/takashi/Library/CloudStorage` を追加する必要がある。

```
Docker Desktop → Settings → Resources → File sharing
→ 「+」で /Users/takashi/Library/CloudStorage を追加
→ Apply & Restart
```

さらに **VirtIO ファイル共有** を有効化すると性能が大幅改善:

```
Docker Desktop → Settings → General
→ "Choose file sharing implementation for your containers"
→ "VirtIOFS" を選択
→ Apply & Restart
```

`gRPC-FUSE` だと多ファイルの read で 2-5 倍遅くなる。

## 2.8 開発フロー (Hot reload)

開発中は SPA ソースをリビルドせず Vite の HMR を使いたい。`docker compose.dev.yml` (override) を作る:

```yaml
# docker/docker-compose.dev.yml
services:
  gui:
    build:
      target: builder   # ランタイムでなくビルドステージを使う
    command: ["bun", "run", "dev"]   # vite dev サーバ
    volumes:
      - ../gui-web:/app
      - /app/node_modules   # コンテナ内の node_modules を保護
    environment:
      NODE_ENV: development
```

開発時:
```bash
docker compose -f docker/docker-compose.yml \
               -f docker/docker-compose.dev.yml \
               up
```

本番ビルド時:
```bash
docker compose -f docker/docker-compose.yml up --build
```

## 2.9 ビルド最適化のヒント

- **BuildKit** を有効化 (Docker Desktop なら標準で ON)
- `docker/gui.Dockerfile` の `bun install` は **依存ファイル変更時のみ走る**ように先頭に配置
- `.dockerignore` を作って不要ファイルを除外:

```
# .dockerignore
**/node_modules
**/.git
**/.venv
**/__pycache__
**/.pytest_cache
**/dist
**/.DS_Store
media/
library/
converted/
*.log
.env
```

これでビルド時のコンテキスト送信が高速化される。

## 2.10 トラブルシューティング

| 症状 | 対処 |
|---|---|
| `LIBRARY_PATH must be set` | `.env` を作成して `LIBRARY_PATH=...` を記述 |
| マウントしたパスが空に見える | Docker Desktop の File Sharing 設定を確認 |
| 起動が遅い (5 秒以上) | VirtIOFS を有効化 |
| `bun install` で失敗 | `gui-web/bun.lockb` を一旦削除して再生成 |
| ポート競合 (7860 already in use) | `lsof -i :7860` で確認、`docker compose down` |
| 変換が遅い | `FFMPEG_VARIANTS=240p` まで絞る、`-w 4` で並列増 |
