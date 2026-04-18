# プロジェクト運用ルール（hls-video-player）

親ディレクトリの `/Users/takashi/claude/CLAUDE.md` に加え、このプロジェクト特有のルールを以下に定めます。

## ファイル保全

### `media/source/` — ユーザーの原本、絶対に削除しない

- `.mp4 / .mov / .mkv / .webm` はユーザーが配置した **変換元の原本**。再取得コストが高い場合がある。
- アシスタントは **自分が同一セッションで生成したと明確に識別できるファイル以外を削除してはならない**。
  - 判断に迷う場合は削除せず、ユーザーに確認する。
- ワイルドカード `rm`（例: `rm -f media/source/*.mp4`）は禁止。
- E2E 検証で追加のサンプル動画が必要な場合:
  1. 既存の `demo-*.mp4` を再利用するか、
  2. `/tmp/` など `media/` 外の一時領域に生成して、ホスト側で完結させる。

### `media/hls/` / `media/sprites/`

- 変換由来のキャッシュ。削除は可能だが、削除前にユーザーに一言断る（再変換に CPU 時間が掛かるため）。

### 禁止コマンド（例）

```bash
# NG: 一括削除
rm -rf media/source/*
rm -f media/source/*.mp4

# NG: 不明ファイルを「掃除」
rm media/source/<知らない.mp4>

# OK: 自分がこのセッションで明示的に作ったものだけ、フルパスで消す
rm /Users/takashi/claude/hls-video-player/media/source/_scratch-<uuid>.mp4
```

## 変換処理

- CPU / メモリ抑制は `FFMPEG_THREADS` / `FFMPEG_PRESET` / `FFMPEG_NICE` と docker の `deploy.resources.limits` で制御。詳細は README の「リソース制限」セクション参照。
- 画面からの変換は `POST /api/sources/:filename/convert` → ジョブ登録簿でポーリング。`/api/jobs/:id` が進捗率 (0..1) と stage を返す。
