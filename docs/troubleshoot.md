# トラブルシューティング (Docker Web 版)

## 起動・環境

### `LIBRARY_PATH is missing a value`
`.env` が無い、または `make` を使わず `--env-file .env` を付けていない。

```bash
cp .env.example .env
$EDITOR .env        # LIBRARY_PATH=... を設定
make up
```

`make` を使わない場合:
```bash
docker compose --env-file .env -f docker/docker-compose.yml up
```

### マウントしたフォルダが空に見える / `library_root_exists: false`
Docker Desktop の File Sharing 設定にパスが入っていない。

```
Docker Desktop → Settings → Resources → File sharing
→ /Users/<you>/Library/CloudStorage を追加 → Apply & Restart
```

### 起動が遅い / ファイル読み込みが重い
Docker Desktop のファイル共有方式を VirtIOFS にする。

```
Docker Desktop → Settings → General
→ "Choose file sharing implementation" → VirtIOFS → Apply & Restart
```

### ポート 7860 が競合
```bash
lsof -i :7860              # 誰が使っているか
make down                  # 既存コンテナを停止
# それでも競合するなら .env に PORT=7870 等を追加
```

### `docker compose config` がエラー
`--env-file .env` が必要。`make config` を使う。

## 動画が表示されない

### `/api/videos` が空 ([])
- ライブラリに `converted/<stem>/` が無い → まず変換が必要
  - TS結合管理タブの「🎬 HLS 変換実行」or CLI `hls-convert <path> -w 4`
- 設定タブで正しいライブラリパスを指定しているか確認
- `converted/<stem>/` に `hls/master.m3u8` `thumbs/poster.png` `meta.json` の 3 点が揃っているか
  - 揃っていなければ中断分。`hls-convert <path>` で再変換 (自動検出)

### サムネが出ない
- `/library/<stem>/thumbs/poster.png` をブラウザで直接開いて 200 か確認
- 404 なら変換が未完了。再変換する

### グリッドがカクつく / 固まる
- Docker on macOS の I/O 遅延。VirtIOFS を有効化
- それでも遅い場合は `make logs` でエラーを確認

## 再生できない

### プレイヤーが真っ黒
- `/library/<stem>/hls/master.m3u8` が 200 を返すか確認
- ブラウザのコンソールでエラーを確認
- Video.js は動的ロード。ネットワークタブで `video.js` チャンクが読めているか

### 「動画が見つかりません」
- URL の stem が `/api/videos` の id と一致しているか
- 一覧をリロード (設定変更後など)

## 変換が動かない

### 「変換実行」を押しても進まない
- converter コンテナが起動しているか: `make ps`
- converter のログ: `docker compose --env-file .env -f docker/docker-compose.yml logs -f converter`
- `<LIBRARY>/.jobs/` に `<id>.json` が作られているか
- converter が `<id>.status.json` を更新しているか

### ログ streaming が止まる
- WebSocket 切断。ページをリロードして再購読
- ジョブ自体は converter コンテナで継続している (job status で確認)

### 変換が極端に遅い
- Docker on macOS は NVENC 不可 → CPU エンコード
- `docker/docker-compose.yml` の converter 環境変数で
  `FFMPEG_VARIANTS=240p` まで絞る、`FFMPEG_PRESET=ultrafast`

## お気に入り

### Python 版と同期しない
- 両者は同じ `<LIBRARY>/favorites.json` を読む
- Docker 版で変更 → Python 版はタブ切替/再スキャンで反映
- Python 版で変更 → Docker 版はページリロードで反映
- 同時に大量トグルしても atomic rename で破損しない設計

## Drive FUSE 固有

### ★ 重要: サムネが全部黒い / 再生できない / リンク切れが大量
**症状**: `/api/videos` は件数を返すのにサムネが全て黒、HLS も再生不可。
GUI 上部に「⚠ ファイル本文の読み込みに失敗しています」バナーが出る。

**原因 (確定)**: Google Drive **CloudStorage** フォルダを Docker に
bind mount すると、**ファイル本文の read が `EDEADLK`
(Resource deadlock avoided) で deadlock** する。
Docker Desktop の VirtioFS と Google Drive の FUSE が二重 FUSE になり、
`stat` (サイズ取得) は通るが `read` (本文) が失敗する macOS 固有の問題。
リトライしても回復しない。`/api/health` の `file_read.ok` が `false` になる。

**回避策 (いずれか)**:

1. **ローカルフォルダを使う (推奨)**
   Drive 外のローカル SSD にライブラリを置き、`LIBRARY_PATH` をそこに向ける。
   既存の Drive ライブラリは `make mirror` でローカルへ複製できる:
   ```bash
   # .env の LIBRARY_PATH (Drive) の converted/ → ローカル ./local-library へ rsync
   # (原本 mp4 等は複製しない。Web 版は HLS 再生なので不要)
   make mirror
   # .env を local-library に向けて再起動
   #   LIBRARY_PATH=/Users/<you>/claude/hls-video-player/local-library
   make restart
   ```
   Drive は原本保管庫として残り、Docker はローカルを読むので高速・安定。

2. **Python 版 `ts-merge --gui` を使う (Drive 用)**
   ホストネイティブで動くため Drive FUSE を正しく読める。
   Drive 常駐ライブラリの閲覧はこちら、ローカルライブラリは Docker 版、
   と使い分ける (favorites.json は両者で共有)。

3. **変換出力だけローカルに分離**
   原本 mp4 は Drive、`converted/` のみローカルへ。
   Docker は `converted/` を読めれば再生・サムネは動く。

> Docker 版は **ローカルフォルダで全機能が正常動作**することを検証済み
> (`/tmp/...` のような Drive 外パス)。問題は Drive+Docker の組合せのみ。

### `OSError: [Errno 89] Operation canceled`
Drive がファイル同期中の read 失敗。Python 版で発生。
- catch して空扱いで継続 (ハングしない)
- 数秒待ってリロードで解消することが多い

### 初回アクセスが遅い (数十秒〜数分)
Drive がファイルをローカルにダウンロードする待ち時間 (Python 版)。
- Docker 版の場合は上記「サムネが全部黒い」を参照 (こちらは遅延でなく不可)

## クリーンアップ

### 完全削除 (ホストに何も残さない)
```bash
make clean                                    # コンテナ + volume 削除
docker rmi hls-video-player-gui hls-video-player-converter
# Drive 側の動画 / favorites.json は触らない (Drive にある)
```

### イメージ再ビルド
```bash
make build           # キャッシュ利用
# 完全クリーンビルド:
docker compose --env-file .env -f docker/docker-compose.yml build --no-cache
```

## ログの見方

```bash
make logs                              # gui のログを tail
docker compose --env-file .env -f docker/docker-compose.yml logs -f converter
make ps                                # コンテナ状態 + health
docker stats hls-gui hls-converter     # CPU/メモリ
curl http://localhost:7860/api/health  # ヘルスチェック
```

## それでも解決しない

1. `make logs` と `docker compose ... logs converter` の出力を確認
2. `curl http://localhost:7860/api/health` の結果
3. `make config` でコンポーズ定義が正しいか
4. Docker Desktop を再起動 (`Quit` → 再起動)
5. `make clean && make up` でフルリセット
