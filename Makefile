# HLS Video Player — Docker 操作の便利ターゲット
# (docker/ 配下の compose ファイルがルートの .env を自動検出しないため
#  --env-file を毎回つけるのを Makefile で隠蔽する)

COMPOSE := docker compose --env-file .env -f docker/docker-compose.yml
COMPOSE_DEV := $(COMPOSE) -f docker/docker-compose.dev.yml

.PHONY: help up down build dev logs restart ps config clean mirror

help:
	@echo "make up      — 本番モードで起動 (http://localhost:7860)"
	@echo "make dev     — 開発モード (Vite HMR, http://localhost:5173)"
	@echo "make down    — 停止"
	@echo "make build   — イメージ再ビルド"
	@echo "make logs    — gui ログを tail"
	@echo "make restart — gui を再ビルドして再起動"
	@echo "make ps      — コンテナ状態"
	@echo "make config  — compose 設定の検証"
	@echo "make clean   — コンテナ + ボリューム削除"
	@echo "make mirror  — Drive の converted/ を ./local-library へ rsync"
	@echo "               (Docker+Drive FUSE の EDEADLK 回避用・原本mp4は除外)"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

dev:
	$(COMPOSE_DEV) up

logs:
	$(COMPOSE) logs -f gui

restart:
	$(COMPOSE) up -d --build gui

ps:
	$(COMPOSE) ps

config:
	$(COMPOSE) config --quiet && echo "OK"

clean:
	$(COMPOSE) down -v

mirror:
	@set -a; . ./.env; set +a; \
	test -n "$$LIBRARY_PATH" || (echo "LIBRARY_PATH 未設定"; exit 1); \
	mkdir -p ./local-library; \
	echo "rsync: $$LIBRARY_PATH/ → ./local-library/ (converted/ + index.md + favorites.json)"; \
	echo "  ※ 原本 mp4 等は複製しません (Web 版は HLS 再生なので不要・原本は Drive に温存)"; \
	echo "  ※ 進捗は別端末で: watch 'find ./local-library -type f | wc -l'"; \
	rsync -a \
	  --include='converted/***' \
	  --include='index.md' \
	  --include='favorites.json' \
	  --exclude='*' \
	  "$$LIBRARY_PATH/" ./local-library/ || { echo "rsync 失敗"; exit 1; }; \
	echo ""; \
	echo "完了。 .env を以下に変更して make restart:"; \
	echo "  LIBRARY_PATH=$$PWD/local-library"
