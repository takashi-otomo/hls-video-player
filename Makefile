# HLS Video Player — Docker 操作の便利ターゲット
# (docker/ 配下の compose ファイルがルートの .env を自動検出しないため
#  --env-file を毎回つけるのを Makefile で隠蔽する)

COMPOSE := docker compose --env-file .env -f docker/docker-compose.yml
COMPOSE_DEV := $(COMPOSE) -f docker/docker-compose.dev.yml

.PHONY: help up down build dev logs restart ps config clean

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
