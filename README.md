# HLS Video Player

MP4 / TS ソースを HLS（HTTP Live Streaming）に変換し、ブラウザ上で **アダプティブビットレート再生** と **シークバー上のサムネイルプレビュー** を実現する動画ライブラリアプリ。

---

## 🚀 推奨: Docker Web 版 (Bun + Svelte)

ホストを汚染せず Docker だけで動く Web GUI。**新規利用はこちらを推奨**します。

```bash
# 1. 動画フォルダのパスを .env に設定
cp .env.example .env
$EDITOR .env          # LIBRARY_PATH=/path/to/your/library

# 2. 起動 (Docker Desktop が必要)
make up               # → http://localhost:7860

# その他
make dev              # 開発モード (Vite HMR, http://localhost:5173)
make down             # 停止
make logs             # ログ
make restart          # 再ビルドして再起動
make clean            # コンテナ + ボリューム削除
```

| 機能 | 内容 |
|---|---|
| ライブラリ | グリッド表示・サムネ・ホバー slideshow・お気に入り・フィルタ |
| プレイヤー | HLS 再生・前/次ナビ・★・キーボード ←→ F Esc |
| TS結合管理 | index.md 編集・状態一覧・TSパート削除 |
| 変換 | HLS 変換 / TS 結合をブラウザから実行 (ログ WebSocket streaming) |
| PWA | ブラウザの「インストール」でドック登録可能 |

- ホスト依存: **Docker Desktop のみ** (Bun / Node.js / Python / ffmpeg は全てコンテナ内)
- 設計詳細: [docs/migration-plan/](docs/migration-plan/README.md)
- 構成: `gui` (Bun+Hono+Svelte) + `converter` (Python+ffmpeg) の 2 コンテナ
- `favorites.json` / `converted/` は Python 版と共有 (並行運用可)
- 困ったときは [docs/troubleshoot.md](docs/troubleshoot.md)

> ⚠ `make` を使わない場合は `docker compose --env-file .env -f docker/docker-compose.yml up` のように `--env-file .env` を必ず付けてください (compose ファイルが `docker/` 配下にあるため)。

---

## CLI ツール (pipx)

変換だけをコマンドラインで行う場合:

```bash
pipx install --force "/path/to/hls-video-player[gui,app]"
hls-convert /path/to/library -w 4     # HLS 変換
ts-merge /path/to/library             # TS 結合
ts-merge --gui /path/to/library       # 旧 Tkinter GUI (非推奨、Docker 版へ移行を)
```

---

## Python + Gradio 版 (レガシー / Colab 用)

以下は Python + Gradio + FastAPI で動作する旧構成です。Google Colab では引き続きこちらを使用します（`colab_launch.ipynb`）。ローカルでの新規利用は Docker Web 版を推奨します。

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

## リソース制限 / 変換パフォーマンス

`docker-compose.yml` の `deploy.resources.limits` と環境変数で 3 層の抑制:

| 変数 | デフォルト | 意味 |
|---|---|---|
| `APP_CPUS` | `2.0` | コンテナ最大 CPU |
| `APP_MEMORY` | `2g` | コンテナ最大メモリ |
| `MAX_CONCURRENT_JOBS` | `2` | 並列変換数 |
| `FFMPEG_THREADS` | `0` (auto) | 各エンコーダのスレッド数。0 = ffmpeg 自動 |
| `FFMPEG_PRESET` | `ultrafast` | libx264 プリセット（CPU encode 時） |
| `FFMPEG_HWACCEL` | `auto` | `auto` / `nvenc` / `cpu`。auto は NVENC 利用可能なら自動選択 |
| `FFMPEG_CUVID` | `off` | `auto` / `on` / `off`。NVENC 時に GPU decode (CUVID) も使うか。環境によって libcuda ロードで落ちるため既定 off |
| `FFMPEG_NVENC_PRESET` | `p4` | h264_nvenc プリセット（`p1`=最速, `p7`=最高画質） |
| `FFMPEG_BFRAMES` | *(未設定)* | NVENC の -bf 値。未設定なら NVENC デフォルト。`0` で B-frames 無効化 |
| `FFMPEG_VARIANTS` | *(空)* | `720p,360p` などでラダーを絞る。未指定は 4 本全部 |
| `FFMPEG_NICE` | `10` | プロセス優先度（Unix 系のみ） |

### 変換速度の目安

内部実装は `-filter_complex split=N` で **デコードを 1 回に抑え**、N 本のバリアントへ分岐します。
NVENC + CUVID の組合せで decode / scale / encode を全て GPU 上で完結させ、メモリコピーを排します。

| 環境 | 実時間あたり変換速度 |
|---|---|
| CPU (libx264, preset=ultrafast) | 1〜2x |
| NVIDIA GPU + CPU decode (h264_nvenc, p4) | 3〜5x |
| NVIDIA GPU + CUVID (+ `scale_cuda`) | **8〜15x**（`FFMPEG_CUVID=auto` + `LD_LIBRARY_PATH` 適切時） |

### Colab T4 での CUVID 有効化

Colab T4 ランタイムは `libcuda.so.1` / `libnvcuvid.so.1` を **`/usr/lib64-nvidia/`** に
配置しますが、`ldconfig` のサーチパスから外れているため apt ffmpeg の `dlopen()` が
失敗します。Python プロセス起動前に下記を設定すれば解決します:

```python
import os
os.environ["LD_LIBRARY_PATH"] = "/usr/lib64-nvidia:" + os.environ.get("LD_LIBRARY_PATH", "")
```

`colab_launch.ipynb` のセル 2 で自動設定済み。設定後 `FFMPEG_CUVID=auto` で CUVID が
自動選択されます（対応 codec = h264 / hevc / vp9 / av1 等）。

### 軽量化プリセット

```bash
# CPU 優先 / 低解像度のみ
FFMPEG_THREADS=1 FFMPEG_PRESET=ultrafast FFMPEG_VARIANTS=720p,360p \
  MAX_CONCURRENT_JOBS=1 APP_CPUS=1.0 docker compose up

# NVIDIA GPU（ローカル / Colab T4）: 既定で auto 検出。明示するなら
FFMPEG_HWACCEL=nvenc FFMPEG_NVENC_PRESET=p4 ...
```

Colab では **ランタイム > ランタイムのタイプを変更 > T4 GPU** を選ぶと NVENC が自動で有効になります。

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

`colab_launch.ipynb` を Colab で開き、上から順に実行するだけで起動します。
**コードベースは Git ではなく Google Drive に置いたコピーから取得**、メディアも Drive に永続化します。

### 事前準備（初回のみ）

Google Drive に次のレイアウトでコードを配置:

```
MyDrive/
└── hls-video-player/
    ├── pyproject.toml
    ├── app/
    ├── hls_video/
    ├── static/
    └── media/
        ├── source/   ← 変換元 MP4 を置く（永続）
        ├── hls/      ← 変換出力（永続、再生成可能）
        └── sprites/  ← スプライト + VTT（永続、再生成可能）
```

手元の `hls-video-player/` ディレクトリをそのまま Drive にアップロードすれば OK。`.git/`、`.venv/`、`node_modules/`、`__pycache__/` は不要（ノート側で除外コピー）。

### 実行フロー

1. **FFmpeg + Python 依存**: `apt install ffmpeg` / `pip install gradio fastapi uvicorn python-multipart`
2. **Drive マウント**: `drive.mount('/content/drive')`
3. **Google Drive からコードベースをコピー**:
   - コード: `/content/drive/MyDrive/hls-video-player` → `/content/hls-video-player` （`.git`, `__pycache__`, `.venv`, `media/` は除外）
   - メディア: `/content/hls-video-player/media` → `/content/drive/MyDrive/hls-video-player/media` の **シンボリックリンク**
     → アプリは Colab ローカルで動き、動画の実体は Drive に永続化
4. **Python パッケージとしてインストール**: `pip install -e .`
5. **`MEDIA_ROOT` 設定**: `{LOCAL_ROOT}/media`（symlink 経由で Drive を指す）
6. **起動 (外部アクセス可)**:
   - FastAPI (Gradio + `/hls` + `/sprites` + `/api` + `/player`) を port 7860 で立ち上げ
   - Gradio の `setup_tunnel` で `*.gradio.live` の公開 URL を発行
   - `demo.launch(share=True)` だと Gradio 単体用の別サーバが立ち、`/hls/*` 等が share URL で見えなくなる。本方式なら全ルートが 1 本の URL 配下でアクセス可能

### コード更新時（Drive 同期）

手元で編集 → `scripts/sync-to-drive.sh` 実行 → Colab でノートを先頭から再実行。

```bash
# Mac の Google Drive for desktop が /Users/takashi/Google Drive/マイドライブ を
# 提供している前提。別パスなら HLS_DRIVE_DEST か第 1 引数で指定。
./scripts/sync-to-drive.sh                 # 既定パスへ rsync
./scripts/sync-to-drive.sh --dry-run       # 何がコピーされるか事前確認
./scripts/sync-to-drive.sh --delete        # Drive 側の余剰ファイルも削除
./scripts/sync-to-drive.sh "/path/to/dst"  # 宛先を上書き
```

除外: `.git/`、`.venv/`、`__pycache__/`、`*.egg-info/`、`.DS_Store`、`.gradio/`、`media/`、`node_modules/` 等。
**`media/` は同期対象外** — Drive 側の実体がソース・オブ・トゥルースのため、ローカル変換出力で Drive を汚さない。

### Colab 固有の注意

- **Drive I/O が遅い**: media の入出力は Drive を経由するので、ローカル VM より変換時間が 1.5〜2 倍程度伸びる傾向。コードは Colab ローカルにコピーして使うことで import / reload は高速
- **VM タイムアウト**: 無償枠は 12 時間、アイドル 90 分で切断。進行中ジョブは途中で停止しうるため、大きな動画は一度に 1 本ずつ
- **share URL は一時的**: セッション切断と同時に無効化。業務利用には向かない

## 開発ルール

- TDD: `tests/test_<module>.py` を先に書き、実装でグリーン化
- `media/source/` のユーザー原本は絶対に削除しない（CLAUDE.md 参照）
- コミット単位は 1 ファイル≒1 責務

## ライセンス

Private / Internal Use
