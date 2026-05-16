# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY hls_video/ ./hls_video/
COPY app/ ./app/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -e .

ENV LIBRARY_ROOT=/library
ENV FFMPEG_HWACCEL=cpu
ENV FFMPEG_PRESET=ultrafast
ENV FFMPEG_AUDIO_COPY=1
ENV FFMPEG_VARIANTS=720p,360p

COPY docker/converter-entry.py /usr/local/bin/converter-entry
RUN chmod +x /usr/local/bin/converter-entry

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "/usr/local/bin/converter-entry"]
