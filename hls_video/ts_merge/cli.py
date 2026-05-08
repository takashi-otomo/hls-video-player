"""`ts-merge` コマンドのエントリポイント。

ディスパッチ:
    ts-merge --gui [folder]            → Tkinter GUI 起動
    ts-merge [folder] [-w N] [...]     → CLI で TS 結合 (旧 ts_merge_colab.py 相当)

GUI / CLI で対象フォルダのオプションは共通 (folder 位置引数)。
"""

from __future__ import annotations

import argparse
import sys


def _build_root_parser() -> argparse.ArgumentParser:
    """`--gui` の有無だけを先に判定する軽量 parser。"""
    p = argparse.ArgumentParser(
        prog="ts-merge",
        description=(
            "TS パートを結合して MP4 を作成する CLI / GUI ツール。"
            " `--gui` でステータス管理 GUI を起動し、HLS 変換状態の確認・サムネ表示・"
            " ブラウザでの再生も行える。"
        ),
        add_help=False,  # サブコマンド側で help を扱うため一旦無効
    )
    p.add_argument("--gui", action="store_true", help="Tkinter GUI を起動する")
    p.add_argument("--debug", action="store_true", help="デバッグログを stderr へ")
    p.add_argument(
        "--start-player", action="store_true",
        help="(--gui と併用) 同プロセスで FastAPI プレイヤーサーバを起動",
    )
    p.add_argument(
        "--player-port", type=int, default=7860,
        help="(--gui) プレイヤーサーバのポート (既定 7860)",
    )
    p.add_argument(
        "--api-port", type=int, default=8765,
        help="(--gui) ステータス HTTP API のポート (既定 8765)",
    )
    p.add_argument(
        "--index", type=str, default=None,
        help="(--gui) index.md のパス (省略時は <folder>/index.md)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # 1) --gui を含むかどうかを優先判定 (含まない引数は merge 側に丸投げ)
    if "--gui" in argv:
        # GUI 用の引数だけ抜き出す。残り (folder のみ) を渡す。
        gui_parser = _build_root_parser()
        gui_parser.add_argument(
            "folder", nargs="?", default=".",
            help="対象フォルダ (デフォルト: カレント)",
        )
        gui_parser.add_argument(
            "-h", "--help", action="help", default=argparse.SUPPRESS,
            help="このヘルプを表示",
        )
        args = gui_parser.parse_args(argv)
        from hls_video.ts_merge.gui import run_gui
        return run_gui(
            folder=args.folder,
            index_file=args.index,
            api_port=args.api_port,
            player_port=args.player_port,
            start_player=args.start_player,
            debug_enabled=args.debug,
        )

    # 2) CLI モード: --help はここで分岐 (root + merge の説明をまとめる)
    if "-h" in argv or "--help" in argv:
        # メイン CLI の使い方 + GUI ヒントを出す
        from hls_video.ts_merge.merge import build_parser
        merge_parser = build_parser()
        merge_parser.epilog = (
            "GUI モード:\n"
            "  ts-merge --gui [folder]       Tkinter GUI を起動\n"
            "  ts-merge --gui --start-player [folder]   GUI + プレイヤーサーバを起動"
        )
        merge_parser.formatter_class = argparse.RawDescriptionHelpFormatter
        merge_parser.parse_args(["--help"])
        return 0

    # 3) CLI 結合実行
    from hls_video.ts_merge.merge import main as merge_main
    return merge_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
