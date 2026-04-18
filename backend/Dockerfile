FROM node:22-alpine

# FFmpeg / ffprobe 同梱（HLS 変換とスプライト生成で使用）
RUN apk add --no-cache ffmpeg tini

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev && npm cache clean --force

COPY src ./src
COPY scripts ./scripts

ENV PORT=3000
ENV MEDIA_ROOT=/media
# nginx が静的配信する場合は空文字にすると backend 側の static 配信を無効化
ENV FRONTEND_ROOT=

EXPOSE 3000
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "src/index.js"]
