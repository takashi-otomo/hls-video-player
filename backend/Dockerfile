FROM node:22-alpine

RUN apk add --no-cache ffmpeg

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY src ./src
COPY scripts ./scripts

ENV PORT=3000
ENV MEDIA_ROOT=/media
ENV FRONTEND_ROOT=/frontend

EXPOSE 3000
CMD ["node", "src/index.js"]
