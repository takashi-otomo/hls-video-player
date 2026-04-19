# HLS Video Player (Python + Gradio)

MP4 ソースを HLS（HTTP Live Streaming）に変換し、ブラウザ上で **アダプティブビットレート再生** と **シークバー上のサムネイルプレビュー** を実現する動画再生アプリ。

本プロジェクトは Python + Gradio + FastAPI で動作します。ローカル Docker と Google Colab の両方で同一コードが動きます。

## 特徴

- **MP4 → HLS 変換**: FFmpeg で 720p / 480p / 360p / 240p の 4 段階 ABR ラダーを生成
- **マルチシート スプライト**: 長尺動画（1000+ 秒）でもスプライト画像を自動分割、再生側でシート切替
- **Video.js + VHS**: 追加プラグインなしでクロスブラウザに HLS を再生、16:9 固定、画質セレクタ、シークバーサムネイル
- **Gradio UI**: カード / リスト表示、ファイルアップロード、変換ボタン、並列キュー、進捗バー
- **Google Drive 対応**: MEDIA_ROOT を環境変数で切替、Colab では Drive マウント
- **並列変換**: `MAX_CONCURRENT_JOBS` で同時実行数を設定可

## プロジェクト構成

```
hls-video-player/
├── pyproject.toml
├── Dockerfile                  # python:3.11-slim + ffmpeg + tini
├── docker-compose.yml          # 単一 app サービス（ポート 7860）
├── docker-compose.override.yml # dev: ソースバインドマウント + uvicorn --reload
├── colab_launch.ipynb          # Colab ワンクリック起動（Phase 4）
├── app/                        # Gradio + FastAPI
│   ├── main.py                 # エントリ: python -m app.main
│   ├── gradio_ui.py            # Blocks UI (@gr.render + gr.Timer)
│   ├── static_mount.py         # /hls, /sprites, /static のマウント + MIME 設定
│   └── player_embed.py         # /player/{id}, /api/videos/{id}, iframe 埋込
├── hls_video/                  # 再利用可能なコアロジック（pytest 対応）
│   ├── config.py               # 環境変数パラメータ取得
│   ├── ffmpeg_runner.py        # subprocess + nice ラッパ、ffprobe
│   ├── hls_converter.py        # 4 variant ABR の FFmpeg コマンド組立
│   ├── sprite_generator.py     # tile フィルタ + multi-sheet + VTT/JSON 出力
│   ├── video_catalog.py        # 変換済み動画の一覧 + multi-sheet 解決
│   ├── source_catalog.py       # media/source/ 走査 + sprite 埋込
│   ├── job_registry.py         # 並列ジョブキュー (ThreadPoolExecutor)
│   ├── conversion_runner.py    # probe/hls/sprite ステージ加重進捗
│   ├── progress_parser.py      # FFmpeg stderr の time= 抽出
│   ├── master_playlist.py      # master.m3u8 組立
│   ├── vtt_builder.py          # スプライト座標計算 + WebVTT 組立
│   └── cli.py                  # 動作確認用 CLI
├── static/
│   ├── playerFactory.js        # Video.js 初期化、シークバーサムネ、画質セレクタ
│   └── player.css
├── tests/                      # pytest (89 件)
└── media/
    ├── source/                 # 変換元 MP4 を置く
    ├── hls/                    # 変換後 HLS 出力
    └── sprites/                # スプライト + VTT + JSON
```

## クイックスタート（Docker）

```bash
docker compose up -d --build
open http://localhost:7860
```

停止:
```bash
docker compose down
```

ログ:
```bash
docker compose logs -f app
```

## クイックスタート（ローカル Python）

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[app,dev]"
MEDIA_ROOT=./media .venv/bin/python -m app.main
```

## テスト

```bash
pytest
```

89 件のテストが通ります:
- `test_config` (8), `test_progress_parser` (9), `test_master_playlist` (4)
- `test_vtt_builder` (11), `test_ffmpeg_runner` (6), `test_hls_converter` (6)
- `test_sprite_generator` (8), `test_video_catalog` (6), `test_source_catalog` (10)
- `test_job_registry` (10, 並列キュー検証含む), `test_conversion_runner` (4)
- `test_integration` (7, FastAPI + 静的マウント)

## CLI での変換

Gradio UI を使わずコマンドラインから変換:

```bash
MEDIA_ROOT=./media .venv/bin/python -m hls_video.cli media/source/movie.mp4
```

## 使い方（UI）

1. **アップロード**: 画面上部の領域に MP4/MOV/MKV/WEBM をドロップ → `media/source/` に保存
2. **変換**: カード/行の「変換」ボタン → ステージ加重の進捗バーが表示される（解析中 → HLS変換中 → サムネイル生成中 → 変換済）
3. **再生**: 「▶ 再生」ボタン → 16:9 の Video.js プレイヤーがロード、画質セレクタとシークバーサムネイルが使用可能

## リソース制限（CPU / メモリ）

`docker-compose.yml` の `deploy.resources.limits` と環境変数で 3 層の抑制:

| 変数 | デフォルト | 意味 |
|---|---|---|
| `APP_CPUS` | `2.0` | コンテナ最大 CPU |
| `APP_MEMORY` | `2g` | コンテナ最大メモリ |
| `MAX_CONCURRENT_JOBS` | `2` | 並列変換数 |
| `FFMPEG_THREADS` | `2` | 各エンコーダのスレッド数 |
| `FFMPEG_PRESET` | `veryfast` | libx264 プリセット |
| `FFMPEG_NICE` | `10` | プロセス優先度（Unix 系のみ） |

軽量化したい場合:

```bash
FFMPEG_THREADS=1 FFMPEG_PRESET=ultrafast MAX_CONCURRENT_JOBS=1 APP_CPUS=1.0 docker compose up
```

## API

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/` | Gradio UI |
| GET | `/hls/:id/master.m3u8` | マスタープレイリスト |
| GET | `/hls/:id/:variant.m3u8` | 解像度別メディアプレイリスト |
| GET | `/hls/:id/:variant_NNN.ts` | セグメント（immutable cache） |
| GET | `/sprites/:id.jpg` | スプライト画像 |
| GET | `/sprites/:id.vtt` | WebVTT |
| GET | `/static/playerFactory.js` | プレイヤー初期化 JS |
| GET | `/player/:id` | Video.js 埋込 HTML（iframe で使用） |
| GET | `/api/videos/:id` | 動画メタ情報 (sheets[] 含む) |

MIME:
- `application/vnd.apple.mpegurl` (`.m3u8`, no-cache)
- `video/mp2t` (`.ts`, immutable cache)
- `text/vtt` (`.vtt`)

## Google Colab で動かす

Phase 4 で `colab_launch.ipynb` を追加予定。Drive をマウントして `MEDIA_ROOT=/content/drive/MyDrive/hls-video/media` に差替え、`python -m app.main` を起動。

## 開発ルール

- TDD: `tests/test_<module>.py` を先に書き、実装でグリーン化
- `media/source/` のユーザー原本は絶対に削除しない（CLAUDE.md 参照）
- コミット単位は 1 ファイル≒1 責務

## ライセンス

Private / Internal Use
