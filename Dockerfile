FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tini curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係のみを先に入れてレイヤキャッシュを効かせる
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[app]"

# 実ソース
COPY hls_video ./hls_video
COPY app ./app
COPY static ./static

ENV PORT=7860 \
    HOST=0.0.0.0 \
    MEDIA_ROOT=/media \
    MAX_CONCURRENT_JOBS=2 \
    FFMPEG_THREADS=2 \
    FFMPEG_PRESET=veryfast \
    FFMPEG_NICE=10 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -fs http://localhost:7860/ > /dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.main"]
