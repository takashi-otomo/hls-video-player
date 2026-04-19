#!/usr/bin/env bash
# ------------------------------------------------------------------
# Sync this codebase to Google Drive (for Colab consumption).
# rsync incremental copy; skips build artifacts, .git, and media/.
#
# 使い方:
#   ./scripts/sync-to-drive.sh                      # 既定パスへ同期
#   ./scripts/sync-to-drive.sh [DEST]               # 任意の宛先
#   ./scripts/sync-to-drive.sh --dry-run            # 変更内容を確認のみ
#   ./scripts/sync-to-drive.sh --delete             # Drive 側の余剰ファイルも削除
#
# 環境変数:
#   HLS_DRIVE_DEST   宛先 Drive パス（CLI 引数が最優先）
# ------------------------------------------------------------------
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_DEST="/Users/takashi/Google Drive/マイドライブ/hls-video-player"

DRY_RUN=0
DELETE=0
DEST=""

for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    --delete)     DELETE=1 ;;
    -h|--help)
      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    --*)          echo "unknown option: $arg" >&2; exit 2 ;;
    *)            DEST="$arg" ;;
  esac
done

DEST="${DEST:-${HLS_DRIVE_DEST:-$DEFAULT_DEST}}"

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync が見つかりません。Xcode Command Line Tools を確認してください。" >&2
  exit 1
fi

parent_dir="$(dirname "$DEST")"
if [ ! -d "$parent_dir" ]; then
  cat >&2 <<EOF
親ディレクトリが見つかりません: $parent_dir
Google Drive for desktop がマウントされているか確認してください。
EOF
  exit 1
fi

mkdir -p "$DEST"

# macOS 同梱の openrsync / BSD rsync と GNU rsync の差を吸収するため、
# 広く共通のフラグのみを使う。
rsync_flags=(-a --human-readable --stats)
[ "$DRY_RUN" -eq 1 ] && rsync_flags+=(--dry-run --itemize-changes)
[ "$DELETE"  -eq 1 ] && rsync_flags+=(--delete --delete-excluded)

# 除外パターン:
# - .git 等の VCS メタ
# - Python / Node の生成物
# - macOS のメタファイル
# - アプリ生成物（media/hls, media/sprites はサイズ大、Colab 側で再生成可能）
# - Colab 側でアプリが symlink を張る都合上、media/ 全体も含めない方が安全
exclude_patterns=(
  '.git/' '.claude/' '.venv/' '.pytest_cache/'
  '__pycache__/' '*.pyc' '*.pyo' '*.egg-info/'
  'node_modules/' 'dist/' 'build/'
  '.DS_Store' '.gradio/' 'flagged/'
  '.env' '.env.local'
  'media/'
)
for p in "${exclude_patterns[@]}"; do
  rsync_flags+=(--exclude "$p")
done

cat <<EOF
========================================
Source: $SRC_DIR/
Dest:   $DEST/
Mode:   $([ "$DRY_RUN" -eq 1 ] && echo 'DRY-RUN ' )$([ "$DELETE" -eq 1 ] && echo 'DELETE   ' || echo 'merge (no delete)')
========================================
EOF

rsync "${rsync_flags[@]}" "$SRC_DIR/" "$DEST/"

echo
echo "✓ 同期完了: $DEST"
if [ "$DRY_RUN" -eq 0 ]; then
  echo
  echo "Colab 側では colab_launch.ipynb を再実行すると最新コードが反映されます。"
fi
