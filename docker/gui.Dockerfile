# syntax=docker/dockerfile:1.7

# === Stage 1: SPA をビルド ===
FROM oven/bun:1.1 AS builder

WORKDIR /app

# bun の lockfile を先に COPY して install をキャッシュ
COPY gui-web/package.json ./
COPY gui-web/bun.lockb* ./
RUN bun install

# ソース投入後にビルド
COPY gui-web/ ./
RUN bun run build

# === Stage 2: ランタイム (Bun サーバ + dist) ===
FROM oven/bun:1.1-slim AS runtime

WORKDIR /app

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/server ./server
COPY --from=builder /app/package.json ./
COPY --from=builder /app/node_modules ./node_modules

ENV LIBRARY_ROOT=/library
ENV PORT=7860
EXPOSE 7860

RUN mkdir -p /config
ENV HLS_SETTINGS_FILE=/config/settings.json

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:7860/api/health || exit 1

CMD ["bun", "run", "server/index.ts"]
