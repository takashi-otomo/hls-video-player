"""TS 動画結合 + ステータス管理 GUI。

`ts-merge` コマンドのエントリポイント。
- `ts-merge [folder]`            → CLI で TS パートを結合 (旧 ts_merge_colab.py 相当)
- `ts-merge --gui [folder]`      → Tkinter GUI で状況可視化 + 再生
- `ts-merge --gui --start-player [folder]`  → GUI 起動 + 同プロセスでプレイヤー起動

GUI は `index.md` (URL リスト) とフォルダ内ファイルを突合し、
さらに `converted/` 配下の HLS 変換状態 / サムネ / 動画再生も統合表示する。
"""

from __future__ import annotations
