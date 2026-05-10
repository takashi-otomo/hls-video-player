"""
TS動画 ステータス管理 GUI (hls-video-player に統合済み)

index.md とフォルダ内ファイルを突合し、TS パートのダウンロード・結合状況を一覧表示。
さらに `converted/` 配下の HLS 変換状態 / サムネイル / 動画再生も統合表示する。

使い方:
  ts-merge --gui [folder]              # GUI 起動
  ts-merge --gui --start-player        # GUI 起動 + 同プロセスでプレイヤーサーバ起動

GUI 機能:
  - TS パート / 結合 MP4 のステータス表示
  - HLS 変換状態 (🎞 HLS済 / ⏳ HLS変換中 / 📼 HLS未変換) を 1 列で可視化
  - converted/{stem}/thumbs/poster.png をサムネとして行頭に表示
  - 「▶ 再生」で http://127.0.0.1:7860/player/{stem} をブラウザで開く
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import parse_qs, urlparse

# Pillow はサムネ表示に必要だが、未インストール環境でも GUI 自体は起動できるよう lazy import
try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_AVAILABLE = True
except Exception:  # noqa: BLE001
    Image = None  # type: ignore
    ImageTk = None  # type: ignore
    _PIL_AVAILABLE = False

# HLS 変換ステータス参照
from hls_video import converted_index
from hls_video.library_converter import (
    CONVERTING_MARKER, output_dir_for, is_already_converted, is_converting,
)
# お気に入り (Web GUI と同じ {library_root}/favorites.json を共有)
from hls_video import favorites as _favorites
from hls_video.thumbnail_generator import THUMB_PERCENTS, thumb_filename

# グリッドカード寸法 (Web /play と同じ 16:9)
_GRID_CARD_W = 240
_GRID_CARD_H = int(_GRID_CARD_W * 9 / 16)   # 135
_GRID_THUMB_W = 220
_GRID_THUMB_H = int(_GRID_THUMB_W * 9 / 16)  # 123 (ceil 124)
# カード全体の高さ: サムネ(123) + タイトル(28) + 長さ(20) + ボタン行(46) + padding
_GRID_CARD_FULL_H = _GRID_THUMB_H + 110
_GRID_CARD_GAP = 12                         # カード間の余白 (px)
_GRID_VIEWPORT_BUFFER_ROWS = 2              # ビューポート上下に余分に描画する行数
_SLIDESHOW_INTERVAL_MS = 700

# --debug フラグ
DEBUG = False
_T0 = time.perf_counter()

# HTTP API デフォルトポート
DEFAULT_API_PORT = 8765


def debug(msg: str):
    """デバッグログ（stderr にタイムスタンプ付き出力）。"""
    if not DEBUG:
        return
    elapsed = time.perf_counter() - _T0
    print(f"[DEBUG {elapsed:8.3f}s] {msg}", file=sys.stderr, flush=True)

# 分割ファイルパターン
PAT_NEW = re.compile(r"^(.+?)_(\d+)-(\d+)\.ts$")  # name_1-3.ts
PAT_OLD = re.compile(r"^(.+?)_part(\d+)\.ts$")      # name_part01.ts
PAT_SPLIT_MP4 = re.compile(r"^(.+?)_(\d+)\.mp4$")   # name_1.mp4, name_2.mp4

# index.md のURLパターン
PAT_INDEX_URL = re.compile(r"https?://[^\s)]+/posts/([a-f0-9-]{36})")


def format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def resolve_index_path(folder: str, index_file: str | None = None) -> Path:
    """index.md のパスを解決する。"""
    if index_file:
        p = Path(index_file)
        return p if p.is_absolute() else Path(folder) / p
    return Path(folder) / "index.md"


def load_index(folder: str, index_file: str | None = None) -> list[dict]:
    """index.md を読み込み、URLとUUIDのリストを返す（順序保持）。

    index_file: 絶対パスまたはfolderからの相対パス。Noneならfolder/index.md。
    """
    index_path = resolve_index_path(folder, index_file)
    debug(f"load_index: path={index_path}")
    if not index_path.exists():
        debug(f"load_index: ファイルなし")
        return []

    entries = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        m = PAT_INDEX_URL.search(line)
        if m:
            uuid = m.group(1)
            url = m.group(0)
            entries.append({"uuid": uuid, "url": url})
    return entries


def add_to_index(
    folder: str, urls: list[str], index_file: str | None = None,
) -> tuple[int, int]:
    """index.md の先頭にURLを追加する。重複はスキップ。

    Returns: (追加数, スキップ数)
    """
    index_path = resolve_index_path(folder, index_file)

    # 既存UUIDを取得
    existing_uuids: set[str] = set()
    existing_content = ""
    if index_path.exists():
        existing_content = index_path.read_text(encoding="utf-8")
        for line in existing_content.splitlines():
            m = PAT_INDEX_URL.search(line)
            if m:
                existing_uuids.add(m.group(1))

    added = 0
    skipped = 0
    new_lines: list[str] = []
    for url in urls:
        m = PAT_INDEX_URL.search(url)
        if not m:
            continue
        uuid = m.group(1)
        if uuid in existing_uuids:
            skipped += 1
            continue
        existing_uuids.add(uuid)
        new_lines.append(url.strip())
        added += 1

    if added > 0:
        prepend = "\n".join(new_lines) + "\n"
        index_path.write_text(prepend + existing_content, encoding="utf-8")

    return added, skipped


def remove_from_index(folder: str, uuids: set[str], index_file: str | None = None) -> int:
    """index.md から指定UUIDを含む行を削除する。削除した行数を返す。"""
    index_path = resolve_index_path(folder, index_file)
    if not index_path.exists():
        return 0

    lines = index_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    removed = 0
    for line in lines:
        m = PAT_INDEX_URL.search(line)
        if m and m.group(1) in uuids:
            removed += 1
        else:
            new_lines.append(line)

    if removed > 0:
        index_path.write_text("".join(new_lines), encoding="utf-8")
    return removed


def scan_folder(folder: str) -> dict:
    """フォルダを走査し、ベース名ごとに分割ファイルと結合済みファイルの情報を返す。"""
    folder_path = Path(folder)
    if not folder_path.is_dir():
        return {}

    groups: dict[str, dict] = {}

    for entry in sorted(folder_path.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".ts"):
            continue

        m = PAT_NEW.match(entry.name)
        if m:
            base = m.group(1)
            part_num = int(m.group(2))
            total = int(m.group(3))
            if base not in groups:
                groups[base] = {"parts": [], "total": total, "format": "new"}
            groups[base]["parts"].append({
                "path": str(entry), "name": entry.name,
                "num": part_num, "size": entry.stat().st_size,
            })
            continue

        m = PAT_OLD.match(entry.name)
        if m:
            base = m.group(1)
            part_num = int(m.group(2))
            if base not in groups:
                groups[base] = {"parts": [], "total": None, "format": "old"}
            groups[base]["parts"].append({
                "path": str(entry), "name": entry.name,
                "num": part_num, "size": entry.stat().st_size,
            })

    for base, info in groups.items():
        info["parts"].sort(key=lambda p: p["num"])
        info["total_size"] = sum(p["size"] for p in info["parts"])
        info["part_count"] = len(info["parts"])

        if info["format"] == "new" and info["total"] is not None:
            expected = set(range(1, info["total"] + 1))
            actual = {p["num"] for p in info["parts"]}
            info["complete"] = actual == expected
            info["missing"] = sorted(expected - actual)
            info["expected_count"] = info["total"]
        else:
            nums = [p["num"] for p in info["parts"]]
            if nums:
                expected = set(range(min(nums), max(nums) + 1))
                info["complete"] = set(nums) == expected
                info["missing"] = sorted(expected - set(nums))
                info["expected_count"] = len(expected)
            else:
                info["complete"] = False
                info["missing"] = []
                info["expected_count"] = 0

        mtimes = [Path(p["path"]).stat().st_mtime for p in info["parts"]]
        info["oldest_mtime"] = min(mtimes) if mtimes else 0

        ts_path = folder_path / f"{base}.ts"
        mp4_path = folder_path / f"{base}.mp4"
        info["merged_ts"] = {
            "exists": ts_path.exists(),
            "size": ts_path.stat().st_size if ts_path.exists() else 0,
            "path": str(ts_path),
        }
        info["merged_mp4"] = {
            "exists": mp4_path.exists(),
            "size": mp4_path.stat().st_size if mp4_path.exists() else 0,
            "path": str(mp4_path),
        }

        # 分割MP4検出 (_1.mp4, _2.mp4, ...)
        split_mp4s = []
        for i in range(1, 10):
            sp = folder_path / f"{base}_{i}.mp4"
            if sp.exists():
                split_mp4s.append({
                    "path": str(sp),
                    "name": sp.name,
                    "num": i,
                    "size": sp.stat().st_size,
                })
            else:
                break
        info["split_mp4s"] = split_mp4s

    # フォルダ内の分割MP4で、まだgroupsに無いベースも検出
    for entry in sorted(folder_path.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".mp4"):
            continue
        m = PAT_SPLIT_MP4.match(entry.name)
        if m:
            base = m.group(1)
            if base not in groups:
                groups[base] = {
                    "parts": [], "total": None, "format": "none",
                    "total_size": 0, "part_count": 0,
                    "complete": True, "missing": [], "expected_count": 0,
                    "oldest_mtime": 0,
                    "merged_ts": {"exists": False, "size": 0, "path": ""},
                    "merged_mp4": {"exists": False, "size": 0, "path": ""},
                    "split_mp4s": [],
                }
                # このベースの分割MP4をまとめて取得
                for i in range(1, 10):
                    sp = folder_path / f"{base}_{i}.mp4"
                    if sp.exists():
                        groups[base]["split_mp4s"].append({
                            "path": str(sp),
                            "name": sp.name,
                            "num": i,
                            "size": sp.stat().st_size,
                        })
                    else:
                        break

    return groups


def scan_folder_with_index(folder: str) -> tuple[list[dict], dict]:
    """index.md + フォルダスキャンを統合したリストを返す。"""
    index_entries = load_index(folder)
    groups = scan_folder(folder)
    folder_path = Path(folder)

    if not index_entries:
        entries = []
        for base in groups:
            entries.append({"uuid": base, "url": "", "has_parts": True})
        return entries, groups

    seen_uuids = set()
    entries = []
    for idx_entry in index_entries:
        uuid = idx_entry["uuid"]
        seen_uuids.add(uuid)

        has_parts = uuid in groups
        mp4_exists = (folder_path / f"{uuid}.mp4").exists()
        ts_single = (folder_path / f"{uuid}.ts").exists()

        # 分割MP4の存在チェック
        split_mp4s = []
        for i in range(1, 10):
            sp = folder_path / f"{uuid}_{i}.mp4"
            if sp.exists():
                split_mp4s.append({
                    "path": str(sp), "name": sp.name,
                    "num": i, "size": sp.stat().st_size,
                })
            else:
                break

        if not has_parts and (mp4_exists or ts_single or split_mp4s):
            groups[uuid] = {
                "parts": [], "total": None, "format": "none",
                "total_size": 0, "part_count": 0,
                "complete": True, "missing": [], "expected_count": 0,
                "oldest_mtime": 0,
                "merged_mp4": {
                    "exists": mp4_exists,
                    "size": (folder_path / f"{uuid}.mp4").stat().st_size if mp4_exists else 0,
                    "path": str(folder_path / f"{uuid}.mp4"),
                },
                "merged_ts": {
                    "exists": ts_single,
                    "size": (folder_path / f"{uuid}.ts").stat().st_size if ts_single else 0,
                    "path": str(folder_path / f"{uuid}.ts"),
                },
                "split_mp4s": split_mp4s,
            }

        entries.append({"uuid": uuid, "url": idx_entry["url"], "has_parts": has_parts})

    for base in groups:
        if base not in seen_uuids:
            entries.append({"uuid": base, "url": "", "has_parts": True})

    return entries, groups


class StatusAPIHandler(BaseHTTPRequestHandler):
    """HTTP API ハンドラー。クラス変数 app_ref で MainApp にアクセスする。"""

    app_ref = None  # MainApp インスタンスへの参照（start_api_server で設定）

    def log_message(self, format, *args):
        # 標準のアクセスログを抑制（デバッグ時のみ stderr へ）
        if DEBUG:
            super().log_message(format, *args)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, msg, status=400):
        self._send_json({"error": msg}, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        app = self.app_ref
        if app is None:
            return self._send_error_json("App not ready", 503)

        url = urlparse(self.path)
        path = url.path
        params = parse_qs(url.query)

        try:
            if path in ("/", "/help"):
                return self._send_json({
                    "endpoints": {
                        "GET /status": "全エントリの集計とフォルダ情報",
                        "GET /entries[?filter=未DL|MP4済|MP4済(TS有)|TS済|未結合|不完全]": "エントリ一覧",
                        "GET /entries/{uuid}": "単一エントリの詳細",
                        "POST /entries": "URLをindex.mdに追加 body:{urls:[...]}",
                        "POST /rescan": "再スキャンを実行",
                    },
                })
            if path == "/status":
                return self._send_json(app.get_status_snapshot())
            if path == "/entries":
                filt = params.get("filter", [None])[0]
                return self._send_json(app.get_entries_snapshot(filter_keyword=filt))
            if path.startswith("/entries/"):
                uuid = path[len("/entries/"):].strip("/")
                if not uuid:
                    return self._send_error_json("Missing uuid", 400)
                detail = app.get_entry_detail(uuid)
                if detail is None:
                    return self._send_error_json(f"Not found: {uuid}", 404)
                return self._send_json(detail)
            return self._send_error_json(f"Unknown path: {path}", 404)
        except Exception as e:
            return self._send_error_json(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):
        app = self.app_ref
        if app is None:
            return self._send_error_json("App not ready", 503)

        url = urlparse(self.path)
        path = url.path

        try:
            if path == "/rescan":
                app.trigger_rescan_from_api()
                return self._send_json({"ok": True, "message": "rescan scheduled"})
            if path == "/entries":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as e:
                    return self._send_error_json(f"Invalid JSON: {e}", 400)
                urls = data.get("urls", [])
                if not isinstance(urls, list):
                    return self._send_error_json("urls must be array", 400)
                result = app.add_urls_from_api(urls)
                return self._send_json(result)
            return self._send_error_json(f"Unknown path: {path}", 404)
        except Exception as e:
            return self._send_error_json(f"{type(e).__name__}: {e}", 500)


def start_api_server(app, port: int):
    """HTTP API サーバーをバックグラウンドスレッドで起動。失敗したら None を返す。"""
    StatusAPIHandler.app_ref = app
    try:
        server = HTTPServer(("127.0.0.1", port), StatusAPIHandler)
    except OSError as e:
        debug(f"API サーバー起動失敗 (port {port}): {e}")
        return None, None
    thread = threading.Thread(
        target=server.serve_forever, name="ts-status-api", daemon=True)
    thread.start()
    debug(f"API サーバー起動: http://127.0.0.1:{port}")
    return server, thread


class MainApp:
    """ステータス管理GUIアプリケーション。"""

    MAX_LOG_LINES = 300

    FILTER_CATEGORIES = [
        "✅ MP4済", "🗑 MP4済(TS有)", "✅ TS済",
        "⏳ 未結合", "⚠ 不完全", "📥 未DL",
    ]

    def __init__(self, folder: str, index_file: str | None = None,
                 api_port: int = DEFAULT_API_PORT,
                 start_player: bool = False, player_port: int = 7860):
        self.folder = folder
        self.index_file = index_file
        self.api_port = api_port
        self.player_port = player_port
        self.groups: dict = {}
        self.entries: list[dict] = []
        self.check_vars: dict[str, tk.BooleanVar] = {}
        self.url_map: dict[str, str] = {}
        self.status_map: dict[str, str] = {}
        self.hls_status_map: dict[str, str] = {}        # uuid -> "done"|"converting"|"none"
        self.mp4_path_map: dict[str, str] = {}
        self.ts_part_path_map: dict[str, str] = {}
        self.disabled_checks: set[str] = set()
        self._api_server = None
        self._api_thread = None
        self._last_scan_at: str | None = None

        # プレイヤーサーバ (FastAPI) — 起動するまで None
        self._player_server = None
        self._player_thread = None
        self._player_running = False
        self._start_player_on_boot = start_player

        # サムネキャッシュ (PhotoImage は GC されないよう参照を保持する必要がある)
        self._thumb_cache: dict[str, "ImageTk.PhotoImage"] = {}        # list view 80x45
        self._poster_cache: dict[str, "ImageTk.PhotoImage"] = {}       # grid 220x123 poster
        self._slideshow_cache: dict[str, list] = {}                    # grid hover 用 6 枚
        # 動画メタ (duration, source_filename 等) — 表示用のキャッシュ
        self._meta_cache: dict[str, dict] = {}

        # スキャン中だけ更新する読み取り専用キャッシュ (毎エントリの stat 回数削減)
        self._converted_dirs: set[str] = set()    # converted/<stem>/ が存在する stem
        self._completed_set: set[str] = set()     # hls-index.json に登録済みの stem (確定 done)
        self._suspicious_dirs: set[str] = set()   # dir はあるが index 未登録 (中断の可能性)
        self._converting_dirs: set[str] = set()   # 旧互換 (現在は未使用)

        # グリッドビュー用
        self._grid_built = False
        self._grid_cards: dict[str, dict] = {}    # uuid -> {frame, thumb_label, fav_btn, ...} (実体化済のみ)
        self._grid_fav_only_var: tk.BooleanVar | None = None
        self._grid_filter_var: tk.StringVar | None = None
        self._favorites_set: set[str] = set()
        # ビューポート遅延描画
        self._grid_layout: list[tuple] = []        # [(uuid, x, y), ...] 全候補の位置 (描画されているとは限らない)
        self._grid_cols: int = 0
        self._grid_total_h: int = 0
        self._grid_render_pending: bool = False
        self._slideshow_loading: set[str] = set()
        # サムネロード用の bounded queue (Drive FUSE でも UI を詰まらせないため)
        import queue as _queue
        self._poster_queue: _queue.Queue = _queue.Queue()
        self._poster_workers_started = False

        debug("Tk() 開始")
        self.root = tk.Tk()
        debug("Tk() 完了")
        self.root.title(f"TS Status — {folder}")
        debug("_build_ui 開始")
        self._build_ui()
        debug("_build_ui 完了")
        self._center_window(1200, 720)
        self._start_api_server()
        if self._start_player_on_boot:
            self._start_player_server()
        debug("_run_scan 開始")
        self._run_scan()

    def _center_window(self, w: int, h: int):
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        # ツールバー
        toolbar = ttk.Frame(self.root, padding=(10, 5))
        toolbar.pack(fill=tk.X)

        self.status_label = ttk.Label(toolbar, text="スキャン中...")
        self.status_label.pack(side=tk.LEFT)

        ttk.Button(toolbar, text="再スキャン", command=self._run_scan).pack(
            side=tk.RIGHT, padx=(5, 0))
        ttk.Button(toolbar, text="📂 Finder", command=self._open_folder).pack(
            side=tk.RIGHT, padx=(5, 0))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.RIGHT, fill=tk.Y, padx=8)

        # プレイヤー関連ボタン
        self.player_btn = ttk.Button(
            toolbar, text="🎬 プレイヤー起動", command=self._toggle_player_server)
        self.player_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self.play_selected_btn = ttk.Button(
            toolbar, text="▶ 選択を再生", command=self._play_selected)
        self.play_selected_btn.pack(side=tk.RIGHT, padx=(5, 0))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.RIGHT, fill=tk.Y, padx=8)

        ttk.Button(toolbar, text="📋 Colabコマンド", command=self._copy_colab_cmd).pack(
            side=tk.RIGHT, padx=(5, 0))
        ttk.Button(toolbar, text="🗑 TSパート削除", command=self._delete_ts_parts).pack(
            side=tk.RIGHT, padx=(5, 0))
        ttk.Button(toolbar, text="📝 index削除", command=self._remove_from_index_checked).pack(
            side=tk.RIGHT, padx=(5, 0))

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.RIGHT, fill=tk.Y, padx=8)

        ttk.Button(toolbar, text="全選択", command=self._select_all).pack(
            side=tk.RIGHT, padx=(5, 0))
        ttk.Button(toolbar, text="全解除", command=self._deselect_all).pack(
            side=tk.RIGHT, padx=(5, 0))

        ttk.Separator(self.root).pack(fill=tk.X)

        # フィルターバー
        filter_bar = ttk.Frame(self.root, padding=(10, 3))
        filter_bar.pack(fill=tk.X)
        ttk.Label(filter_bar, text="フィルター:").pack(side=tk.LEFT, padx=(0, 5))
        self.filter_vars: dict[str, tk.BooleanVar] = {}
        for cat in self.FILTER_CATEGORIES:
            var = tk.BooleanVar(value=True)
            self.filter_vars[cat] = var
            ttk.Checkbutton(
                filter_bar, text=cat, variable=var,
                command=self._apply_filter,
            ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Separator(self.root).pack(fill=tk.X)

        # Notebook でビューを切替: 一覧 (TS結合管理) / グリッド (再生)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        # === Tab 1: 一覧 (既存の TS 管理 UI) ===
        list_tab = ttk.Frame(self.notebook)
        self.notebook.add(list_tab, text="📋 一覧 (TS結合管理)")

        paned = ttk.PanedWindow(list_tab, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 上部: ツリービュー
        tree_frame = ttk.LabelFrame(paned, text="ファイル一覧", padding=5)
        paned.add(tree_frame, weight=3)

        columns = ("check", "status", "hls", "parts", "size", "merged")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="ファイル名", anchor=tk.W)
        self.tree.heading("check", text="", anchor=tk.CENTER)
        self.tree.heading("status", text="状態", anchor=tk.W)
        self.tree.heading("hls", text="HLS", anchor=tk.W)
        self.tree.heading("parts", text="パート数", anchor=tk.W)
        self.tree.heading("size", text="合計サイズ", anchor=tk.W)
        self.tree.heading("merged", text="結合済み", anchor=tk.W)

        # サムネ画像分の余白を #0 に確保
        self.tree.column("#0", width=380, minwidth=240)
        self.tree.column("check", width=50, minwidth=50, stretch=False)
        self.tree.column("status", width=120, minwidth=80)
        self.tree.column("hls", width=110, minwidth=80)
        self.tree.column("parts", width=70, minwidth=50)
        self.tree.column("size", width=90, minwidth=70)
        self.tree.column("merged", width=240, minwidth=150)
        # サムネ画像が大きいので行高を確保
        try:
            style = ttk.Style()
            style.configure("Treeview", rowheight=52)
        except Exception:  # noqa: BLE001
            pass

        tree_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # タグ設定
        self.tree.tag_configure("checked", background="#1b5e20", foreground="white")
        self.tree.tag_configure("unchecked", background="", foreground="")
        self.tree.tag_configure("disabled", background="", foreground="#888")
        self.tree.tag_configure("merged_done", foreground="#66bb6a")
        self.tree.tag_configure("pending", foreground="")
        self.tree.tag_configure("incomplete", foreground="#ff9800")
        self.tree.tag_configure("no_parts", foreground="#e53935")
        self.tree.tag_configure("scanning", foreground="#aaa")
        self.tree.tag_configure("child_mp4", foreground="#4fc3f7")
        self.tree.tag_configure("child_ts", foreground="#999")

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<Double-Button-1>", self._on_tree_double_click)

        # 右クリックメニュー (ベース行用)
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="▶ プレイヤーで再生", command=self._play_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="URLをコピー", command=self._copy_url)
        self.context_menu.add_command(label="ブラウザで開く", command=self._open_url)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="indexから削除", command=self._remove_from_index_single)

        # 右クリックメニュー (TSパート子ノード用)
        self.ts_part_context_menu = tk.Menu(self.root, tearoff=0)
        self.ts_part_context_menu.add_command(
            label="このTSパートを削除", command=self._delete_single_ts_part)
        if sys.platform == "darwin":
            self.tree.bind("<Button-2>", self._on_right_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        # 中部: URL追加エリア
        add_frame = ttk.LabelFrame(paned, text="index.md に URL を追加（1行1URL・複数可）", padding=5)
        paned.add(add_frame, weight=0)

        add_inner = ttk.Frame(add_frame)
        add_inner.pack(fill=tk.BOTH, expand=True)

        self.add_text = tk.Text(
            add_inner, height=3, wrap=tk.NONE, font=("Menlo", 11))
        add_scroll = ttk.Scrollbar(
            add_inner, orient=tk.VERTICAL, command=self.add_text.yview)
        self.add_text.configure(yscrollcommand=add_scroll.set)
        self.add_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        add_btn_frame = ttk.Frame(add_frame)
        add_btn_frame.pack(fill=tk.X, pady=(4, 0))

        self.add_result_label = ttk.Label(add_btn_frame, text="", foreground="gray")
        self.add_result_label.pack(side=tk.LEFT)

        ttk.Button(
            add_btn_frame, text="追加", command=self._add_to_index_inline,
        ).pack(side=tk.RIGHT)

        # 下部: ログ
        log_frame = ttk.LabelFrame(paned, text="ログ", padding=5)
        paned.add(log_frame, weight=1)

        self.log_text = tk.Text(
            log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD, font=("Menlo", 11))
        log_scroll = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # === Tab 2: グリッド (再生) — 中身は遅延構築 ===
        self.grid_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.grid_tab, text="🎞 ライブラリ (グリッド再生)")
        # タブ初表示時に build (1280 件分の widget を最初から作らないため)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ステータスバー
        self.bottom_status = ttk.Label(
            self.root, text=f"フォルダ: {self.folder}",
            padding=(10, 5), foreground="gray")
        self.bottom_status.pack(fill=tk.X, side=tk.BOTTOM)

    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > self.MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{line_count - self.MAX_LOG_LINES}.0")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ─── グリッドビュー (動画再生用、Web /play と同等の UX) ───

    def _on_tab_changed(self, event):
        """タブ変更時: グリッドタブが初めて開かれたら build。"""
        try:
            sel = self.notebook.select()
            if not sel:
                return
            idx = self.notebook.index(sel)
        except tk.TclError:
            return
        # idx 1 = グリッドタブ
        if idx == 1 and not self._grid_built:
            t0 = time.perf_counter()
            self._build_grid_view()
            t1 = time.perf_counter()
            self._grid_built = True
            # populate は async-friendly: layout 計算 → 即 viewport 描画 →
            # favorites は背景で読む
            self._populate_grid()
            t2 = time.perf_counter()
            debug(f"grid: build={int((t1-t0)*1000)}ms populate={int((t2-t1)*1000)}ms")
        elif idx == 1 and self._grid_built:
            # ★ お気に入りはタブ切替の度に背景で再読込 (Drive FUSE で遅延しても UI 止めない)
            self._async_refresh_favorites()

    def _build_grid_view(self):
        """グリッドタブの中身を構築 (Canvas + 内部 Frame + フィルタバー)。"""
        if not _PIL_AVAILABLE:
            ttk.Label(
                self.grid_tab,
                text=("グリッド表示には Pillow が必要です。\n"
                      "  pipx install --force \"<repo>[gui,app]\""),
                padding=20, foreground="orange",
            ).pack()
            return

        # フィルタバー (★お気に入り + 検索 + 更新)
        filter_bar = ttk.Frame(self.grid_tab, padding=(8, 6))
        filter_bar.pack(fill=tk.X)

        self._grid_fav_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filter_bar, text="★ お気に入りのみ",
            variable=self._grid_fav_only_var, command=self._populate_grid,
        ).pack(side=tk.LEFT)

        ttk.Separator(filter_bar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(filter_bar, text="絞り込み:").pack(side=tk.LEFT, padx=(0, 4))
        self._grid_filter_var = tk.StringVar(value="")
        filter_entry = ttk.Entry(filter_bar, textvariable=self._grid_filter_var, width=24)
        filter_entry.pack(side=tk.LEFT, padx=(0, 8))
        filter_entry.bind("<Return>", lambda e: self._populate_grid())
        ttk.Button(
            filter_bar, text="↻ 更新", command=self._populate_grid,
        ).pack(side=tk.RIGHT)
        self._grid_count_label = ttk.Label(
            filter_bar, text="", foreground="gray")
        self._grid_count_label.pack(side=tk.RIGHT, padx=(0, 8))

        # Canvas + scrollbar (縦スクロールのみ)
        canvas_frame = ttk.Frame(self.grid_tab)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        canvas = tk.Canvas(canvas_frame, bg="#0a0c10", highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)

        # スクロール時にビューポート可視範囲のみ描画する仕組み
        def _on_yscroll(*args):
            scrollbar.set(*args)
            # 多数の after が同時にキューイングされないようフラグでデバウンス
            if not self._grid_render_pending:
                self._grid_render_pending = True
                self.root.after_idle(self._render_visible_cards)

        canvas.configure(yscrollcommand=_on_yscroll)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._grid_canvas = canvas

        # 内側の Frame (カードを「絶対座標で place」する土台)
        # widget は viewport に入った時だけ create_window で配置する
        self._grid_inner = tk.Frame(canvas, bg="#0a0c10")
        self._grid_inner_id = canvas.create_window(
            (0, 0), window=self._grid_inner, anchor="nw")

        # canvas の幅変化 → 列数を再計算 → 全レイアウトを組み直し
        def _on_canvas_configure(e):
            canvas.itemconfig(self._grid_inner_id, width=e.width)
            # 列数が変わるので再計算 (描画は遅延)
            if self._grid_built:
                self._recompute_layout()
                self._render_visible_cards()
        canvas.bind("<Configure>", _on_canvas_configure)

        # マウスホイール (macOS では delta が小さい)
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-e.delta / 3), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")

    @staticmethod
    def _make_clickable(label: tk.Label, *, on_click, hover_bg: str, normal_bg: str):
        """tk.Label をクリックボタン化する: ホバーで背景色変化 + クリックで on_click 実行。

        macOS の tk.Button は bg/fg が無視されるため、Label + bind で代用する。
        """
        def _enter(_e):
            try:
                label.configure(bg=hover_bg)
            except tk.TclError:
                pass
        def _leave(_e):
            try:
                label.configure(bg=normal_bg)
            except tk.TclError:
                pass
        def _click(_e):
            try:
                on_click()
            except Exception as exc:  # noqa: BLE001
                debug(f"clickable label callback failed: {exc}")
        label.bind("<Enter>", _enter)
        label.bind("<Leave>", _leave)
        label.bind("<Button-1>", _click)

    @staticmethod
    def _format_duration(s: float) -> str:
        """秒を H:MM:SS / M:SS 形式へ整形 (Web /play と同じ)。"""
        try:
            s = max(0, int(float(s) or 0))
        except (TypeError, ValueError):
            return "—"
        if s <= 0:
            return "—"
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    def _refresh_favorites_set(self):
        """favorites.json を読み直してメモリにキャッシュ (同期、Drive FUSE で遅い可能性あり)。"""
        try:
            self._favorites_set = _favorites.load_favorites(self.folder)
        except Exception as exc:  # noqa: BLE001
            debug(f"favorites load failed: {exc}")
            self._favorites_set = set()

    def _async_refresh_favorites(self):
        """favorites.json を背景スレッドで読み、完了後にカードの ★ 表示を更新。"""
        gen = self._scan_generation

        def _worker():
            t0 = time.perf_counter()
            try:
                favs = _favorites.load_favorites(self.folder)
            except Exception as exc:  # noqa: BLE001
                debug(f"favorites async load failed: {exc}")
                favs = set()
            elapsed = (time.perf_counter() - t0) * 1000
            self.root.after(
                0, lambda f=favs, g=gen, e=elapsed:
                self._on_favorites_loaded(f, g, e),
            )

        threading.Thread(
            target=_worker, name="favs-loader", daemon=True,
        ).start()

    def _on_favorites_loaded(self, favs: set, gen: int, elapsed_ms: float):
        if gen != self._scan_generation:
            return
        self._favorites_set = favs
        debug(f"favorites loaded: {len(favs)} entries ({elapsed_ms:.0f}ms)")
        # 既に描画されているカードの ★ 表示を最新化
        for uuid, card in list(self._grid_cards.items()):
            try:
                is_fav = uuid in favs
                btn = card.get("fav_btn")
                if btn:
                    btn.configure(
                        text=("★ お気に入り済" if is_fav else "☆ お気に入り"),
                        bg=("#3d3320" if is_fav else "#2a2f3a"),
                        fg=("#ffd667" if is_fav else "#c8d0dc"),
                    )
                    # hover 戻り色も更新
                    self._make_clickable(
                        btn,
                        on_click=lambda u=uuid: self._toggle_grid_fav(u),
                        hover_bg=("#4a3f28" if is_fav else "#3a4250"),
                        normal_bg=("#3d3320" if is_fav else "#2a2f3a"),
                    )
            except tk.TclError:
                pass

    def _collect_grid_candidates(self) -> list[str]:
        """フィルタ適用後の候補 UUID リストを返す。"""
        filter_q = (self._grid_filter_var.get() or "").strip().lower() if self._grid_filter_var else ""
        fav_only = bool(self._grid_fav_only_var and self._grid_fav_only_var.get())
        candidates: list[str] = []
        seen_in_entries: set[str] = set()
        for entry in self.entries:
            uuid = entry["uuid"]
            seen_in_entries.add(uuid)
            if uuid not in self._converted_dirs:
                continue
            if fav_only and uuid not in self._favorites_set:
                continue
            if filter_q and filter_q not in uuid.lower():
                continue
            candidates.append(uuid)
        # entries に無い UUID も拾う
        for uuid in sorted(self._converted_dirs - seen_in_entries):
            if fav_only and uuid not in self._favorites_set:
                continue
            if filter_q and filter_q not in uuid.lower():
                continue
            candidates.append(uuid)
        return candidates

    def _calc_grid_cols(self) -> int:
        try:
            canvas_w = max(1, self._grid_canvas.winfo_width())
        except Exception:  # noqa: BLE001
            canvas_w = 1100
        return max(1, canvas_w // (_GRID_CARD_W + _GRID_CARD_GAP))

    def _populate_grid(self):
        """フィルタ変更/初期表示時に呼ばれる。layout を組み立てて viewport だけ描画。

        I/O は一切ブロックしない:
          - favorites.json は背景で読む (_async_refresh_favorites)
          - サムネ画像も別スレッドで遅延ロード
          - layout 計算は純メモリ演算 (1280 件で <10ms)
        """
        if not self._grid_built:
            return
        t0 = time.perf_counter()

        # 既存の widget を全消去 (フィルタ変更時など)
        for w in list(self._grid_inner.children.values()):
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._grid_cards.clear()
        t_destroy = time.perf_counter()

        candidates = self._collect_grid_candidates()
        t_collect = time.perf_counter()
        if not candidates:
            empty = tk.Label(
                self._grid_inner,
                text="(条件に一致する HLS 済み動画がありません)",
                bg="#0a0c10", fg="#8b93a1", padx=20, pady=20, font=("", 12),
            )
            empty.place(x=20, y=20)
            self._grid_layout = []
            self._grid_total_h = 60
            try:
                self._grid_inner.configure(height=60)
                self._grid_canvas.configure(scrollregion=(0, 0, 0, 60))
            except tk.TclError:
                pass
            self._grid_count_label.config(text="")
            return

        # レイアウトのみ計算 (widget は作らない)
        self._grid_candidates = candidates
        self._recompute_layout()
        t_layout = time.perf_counter()
        self._grid_count_label.config(text=f"{len(candidates)} 件")
        # スクロール先頭にリセット
        try:
            self._grid_canvas.yview_moveto(0)
        except tk.TclError:
            pass
        # ビューポートに見える分だけ描画
        self._render_visible_cards()
        t_render = time.perf_counter()
        debug(
            f"_populate_grid: total={int((t_render-t0)*1000)}ms "
            f"(destroy={int((t_destroy-t0)*1000)} "
            f"collect={int((t_collect-t_destroy)*1000)} "
            f"layout={int((t_layout-t_collect)*1000)} "
            f"render={int((t_render-t_layout)*1000)}) "
            f"candidates={len(candidates)}"
        )

        # 背景で favorites を読み込み (Drive FUSE で時間がかかっても UI は止まらない)
        self._async_refresh_favorites()

    def _recompute_layout(self):
        """列数 + カード位置 + scrollregion を再計算 (widget は作らない)。"""
        candidates = getattr(self, "_grid_candidates", [])
        cols = self._calc_grid_cols()
        self._grid_cols = cols
        layout: list[tuple[str, int, int]] = []
        for i, uuid in enumerate(candidates):
            row, col = divmod(i, cols)
            x = col * (_GRID_CARD_W + _GRID_CARD_GAP) + _GRID_CARD_GAP
            y = row * (_GRID_CARD_FULL_H + _GRID_CARD_GAP) + _GRID_CARD_GAP
            layout.append((uuid, x, y))
        self._grid_layout = layout
        rows = (len(candidates) + cols - 1) // cols
        total_h = rows * (_GRID_CARD_FULL_H + _GRID_CARD_GAP) + _GRID_CARD_GAP
        self._grid_total_h = total_h
        try:
            # inner Frame の論理高さ。実 widget は viewport 内のみ存在する。
            self._grid_inner.configure(height=total_h)
            # scrollregion の幅は canvas 幅に追従させる (横スクロールしない)
            canvas_w = max(self._grid_canvas.winfo_width(),
                           cols * (_GRID_CARD_W + _GRID_CARD_GAP) + _GRID_CARD_GAP)
            self._grid_canvas.configure(scrollregion=(0, 0, canvas_w, total_h))
        except tk.TclError:
            pass
        # レイアウトが変わったので既存の widget は座標が古い → 全部破棄して再描画
        for uuid in list(self._grid_cards.keys()):
            self._destroy_card(uuid)

    def _viewport_y_range(self) -> tuple[int, int]:
        """canvas の現在のビューポート (top_y, bottom_y) を返す。"""
        try:
            canvas = self._grid_canvas
            top = int(canvas.canvasy(0))
            bottom = top + max(canvas.winfo_height(), 1)
        except tk.TclError:
            return (0, 0)
        return (top, bottom)

    def _render_visible_cards(self):
        """現在の viewport (+バッファ) に該当する UUID だけ widget を作る。
        範囲外のものは破棄してメモリを解放する。"""
        self._grid_render_pending = False
        if not self._grid_built or not self._grid_layout:
            return

        top, bottom = self._viewport_y_range()
        buffer_px = _GRID_VIEWPORT_BUFFER_ROWS * (_GRID_CARD_FULL_H + _GRID_CARD_GAP)
        top_pad = top - buffer_px
        bottom_pad = bottom + buffer_px

        # 必要な UUID
        needed: set[str] = set()
        for uuid, x, y in self._grid_layout:
            if y + _GRID_CARD_FULL_H < top_pad:
                continue
            if y > bottom_pad:
                break  # layout は y 昇順なので以降不要
            needed.add(uuid)

        # 既存にあって不要になったものを破棄
        for uuid in list(self._grid_cards.keys()):
            if uuid not in needed:
                self._destroy_card(uuid)

        # 新たに必要な分だけ作る
        for uuid, x, y in self._grid_layout:
            if uuid not in needed:
                continue
            if uuid in self._grid_cards:
                continue
            self._render_grid_card_at(self._grid_inner, uuid, x, y)

    def _destroy_card(self, uuid: str):
        card = self._grid_cards.pop(uuid, None)
        if not card:
            return
        # 進行中の slideshow タイマーを止める
        st = card.get("slideshow")
        if st:
            self._cancel_slideshow_step(st)
        try:
            card["frame"].destroy()
        except tk.TclError:
            pass

    def _render_grid_card_at(self, parent, uuid: str, x: int, y: int):
        """指定座標 (x, y) にカードを place で配置。"""
        card = tk.Frame(parent, bg="#1a1d24", padx=2, pady=2,
                        highlightbackground="#272c36", highlightthickness=1)
        card.place(x=x, y=y, width=_GRID_CARD_W, height=_GRID_CARD_FULL_H)

        # サムネ Label (16:9 placeholder)
        thumb = tk.Label(card, bg="#0a0c10", cursor="hand2")
        try:
            placeholder = tk.PhotoImage(width=_GRID_THUMB_W, height=_GRID_THUMB_H)
            thumb.configure(image=placeholder, width=_GRID_THUMB_W, height=_GRID_THUMB_H)
            thumb._placeholder_ref = placeholder  # GC 防止
        except tk.TclError:
            pass
        thumb.pack(pady=(2, 4))

        # タイトル (uuid を縮めて表示) — meta 読込後に source_filename へ差替え
        title_text = uuid[:38] + ("…" if len(uuid) > 38 else "")
        title_label = tk.Label(
            card, text=title_text, bg="#1a1d24", fg="#e6e8eb",
            font=("Menlo", 9), wraplength=_GRID_THUMB_W,
            justify="left", anchor="w",
        )
        title_label.pack(fill=tk.X, padx=6)

        # 動画長 (左寄せ、メタ読込後に更新)
        duration_label = tk.Label(
            card, text="⏱ —", bg="#1a1d24", fg="#8b93a1",
            font=("", 10), anchor="w",
        )
        duration_label.pack(fill=tk.X, padx=6, pady=(2, 0))

        # ボタン行 — macOS の tk.Button は bg を無視するので Label をボタン化する
        btn_row = tk.Frame(card, bg="#1a1d24")
        btn_row.pack(fill=tk.X, padx=6, pady=(6, 6))

        is_fav = uuid in self._favorites_set

        # ★ お気に入りボタン (Label を hand cursor + click 連動)
        fav_btn = tk.Label(
            btn_row,
            text=("★ お気に入り済" if is_fav else "☆ お気に入り"),
            bg=("#3d3320" if is_fav else "#2a2f3a"),
            fg=("#ffd667" if is_fav else "#c8d0dc"),
            font=("Helvetica", 11, "bold"),
            padx=10, pady=6,
            cursor="hand2",
            relief="flat", borderwidth=0,
        )
        fav_btn.pack(side=tk.LEFT)
        self._make_clickable(
            fav_btn,
            on_click=lambda u=uuid: self._toggle_grid_fav(u),
            hover_bg=("#4a3f28" if is_fav else "#3a4250"),
            normal_bg=("#3d3320" if is_fav else "#2a2f3a"),
        )

        # ▶ 再生ボタン (大きく目立つ青のアクションボタン)
        play_btn = tk.Label(
            btn_row,
            text="▶ 再生",
            bg="#1976d2", fg="#ffffff",
            font=("Helvetica", 12, "bold"),
            padx=18, pady=6,
            cursor="hand2",
            relief="flat", borderwidth=0,
        )
        play_btn.pack(side=tk.RIGHT)
        self._make_clickable(
            play_btn,
            on_click=lambda u=uuid: self._play_uuid(u),
            hover_bg="#2196f3",
            normal_bg="#1976d2",
        )

        # サムネクリックで再生
        def _on_thumb_click(e, u=uuid):
            self._play_uuid(u)
        thumb.bind("<Button-1>", _on_thumb_click)

        # ホバーでスライドショー
        slideshow_state = {"idx": 0, "after_id": None, "loaded": False}
        self._bind_card_hover(thumb, uuid, slideshow_state)

        self._grid_cards[uuid] = {
            "frame": card, "thumb": thumb,
            "title_label": title_label,
            "duration_label": duration_label,
            "fav_btn": fav_btn, "play_btn": play_btn,
            "slideshow": slideshow_state,
        }

        # 既にメタが読み込み済みなら即時反映
        meta = self._meta_cache.get(uuid)
        if meta:
            self._apply_meta_to_card(uuid, meta)

        # poster.png + meta.json を背景でロード
        self._enqueue_poster_load(uuid)

    def _bind_card_hover(self, thumb_label, uuid: str, state: dict):
        """サムネにマウスホバーすると poster→05→30→50→60→80→poster をループ。"""
        def _start(_e=None):
            frames = self._slideshow_cache.get(uuid)
            if frames is None:
                # 初ホバー: 6 枚を background で読む。完了後にもう一度 hover で開始可
                self._enqueue_slideshow_load(uuid)
                return
            state["idx"] = 0
            self._cancel_slideshow_step(state)
            _step()

        def _step():
            frames = self._slideshow_cache.get(uuid)
            if not frames:
                return
            try:
                thumb_label.configure(image=frames[state["idx"]])
            except tk.TclError:
                return
            state["idx"] = (state["idx"] + 1) % len(frames)
            state["after_id"] = self.root.after(_SLIDESHOW_INTERVAL_MS, _step)

        def _stop(_e=None):
            self._cancel_slideshow_step(state)
            state["idx"] = 0
            frames = self._slideshow_cache.get(uuid)
            if frames:
                try:
                    thumb_label.configure(image=frames[0])  # poster
                except tk.TclError:
                    pass

        thumb_label.bind("<Enter>", _start)
        thumb_label.bind("<Leave>", _stop)

    def _cancel_slideshow_step(self, state: dict):
        if state.get("after_id") is not None:
            try:
                self.root.after_cancel(state["after_id"])
            except Exception:  # noqa: BLE001
                pass
            state["after_id"] = None

    def _ensure_poster_workers(self, n: int = 4):
        """サムネ + メタ用 worker thread を最大 n 個起動 (起動済みなら何もしない)。
        各 worker は self._poster_queue から uuid を取り出して順次処理する。"""
        if self._poster_workers_started:
            return
        self._poster_workers_started = True

        def _worker_loop():
            while True:
                try:
                    uuid = self._poster_queue.get()
                except Exception:  # noqa: BLE001
                    return
                if uuid is None:
                    return
                out_dir = output_dir_for(uuid, Path(self.folder))

                # 1) meta.json をまず読む (動画長表示に使用)
                if uuid not in self._meta_cache:
                    meta_path = out_dir / "meta.json"
                    try:
                        if meta_path.is_file():
                            meta = json.loads(meta_path.read_text() or "{}")
                            if isinstance(meta, dict):
                                self.root.after(
                                    0, lambda u=uuid, m=meta: self._on_meta_loaded(u, m),
                                )
                    except Exception as exc:  # noqa: BLE001
                        debug(f"meta load failed {uuid}: {exc}")

                # 2) poster.png (なければ thumb_50.jpg) を読み込み
                if uuid not in self._poster_cache:
                    poster = out_dir / "thumbs" / "poster.png"
                    if poster.is_file():
                        src = poster
                    else:
                        fallback = out_dir / "thumbs" / thumb_filename(50)
                        src = fallback if fallback.is_file() else None
                    if src is not None:
                        try:
                            img = Image.open(src)
                            img.thumbnail((_GRID_THUMB_W, _GRID_THUMB_H), Image.LANCZOS)
                            self.root.after(
                                0, lambda i=img, u=uuid: self._on_poster_loaded(u, i),
                            )
                        except Exception as exc:  # noqa: BLE001
                            debug(f"poster load failed {uuid}: {exc}")
                self._poster_queue.task_done()

        for i in range(n):
            threading.Thread(
                target=_worker_loop, name=f"poster-w{i}", daemon=True,
            ).start()

    def _on_meta_loaded(self, uuid: str, meta: dict):
        """meta.json から動画長などを取り出し該当カードに反映 (main thread)。"""
        self._meta_cache[uuid] = meta
        self._apply_meta_to_card(uuid, meta)

    def _apply_meta_to_card(self, uuid: str, meta: dict):
        card = self._grid_cards.get(uuid)
        if not card:
            return
        # 動画長
        try:
            dur_label = card.get("duration_label")
            if dur_label is not None:
                dur_label.configure(text=f"⏱ {self._format_duration(meta.get('duration', 0))}")
        except tk.TclError:
            pass
        # タイトル: source_filename があれば差し替え
        try:
            title_label = card.get("title_label")
            src_name = meta.get("source_filename")
            if title_label is not None and src_name:
                # ファイル名は長くなりがちなので 2 行までで切る
                title_label.configure(text=src_name)
        except tk.TclError:
            pass

    def _enqueue_poster_load(self, uuid: str):
        """poster.png のロードを bounded queue に投入 (UI を詰まらせない)。"""
        if uuid in self._poster_cache:
            self._apply_poster(uuid, self._poster_cache[uuid])
            return
        self._ensure_poster_workers()
        self._poster_queue.put(uuid)

    def _on_poster_loaded(self, uuid: str, img):
        try:
            photo = ImageTk.PhotoImage(img)
        except Exception as exc:  # noqa: BLE001
            debug(f"PhotoImage failed {uuid}: {exc}")
            return
        self._poster_cache[uuid] = photo
        self._apply_poster(uuid, photo)

    def _apply_poster(self, uuid: str, photo):
        card = self._grid_cards.get(uuid)
        if not card:
            return
        try:
            card["thumb"].configure(image=photo)
        except tk.TclError:
            pass

    def _enqueue_slideshow_load(self, uuid: str):
        """ホバー初回: poster + 5 枚を一括ロードして slideshow_cache に格納。"""
        if uuid in self._slideshow_cache:
            return
        # 重複起動を避ける
        if hasattr(self, "_slideshow_loading") and uuid in self._slideshow_loading:
            return
        if not hasattr(self, "_slideshow_loading"):
            self._slideshow_loading = set()
        self._slideshow_loading.add(uuid)

        out_dir = output_dir_for(uuid, Path(self.folder))
        poster = out_dir / "thumbs" / "poster.png"
        thumb_paths = [out_dir / "thumbs" / thumb_filename(p) for p in THUMB_PERCENTS]

        def _worker():
            imgs = []
            try:
                # 順序: poster → 5%, 30%, 50%, 60%, 80%
                for src in [poster, *thumb_paths]:
                    if not src.is_file():
                        continue
                    img = Image.open(src)
                    img.thumbnail((_GRID_THUMB_W, _GRID_THUMB_H), Image.LANCZOS)
                    imgs.append(img)
            except Exception as exc:  # noqa: BLE001
                debug(f"slideshow load failed {uuid}: {exc}")
            if imgs:
                self.root.after(0, lambda: self._on_slideshow_loaded(uuid, imgs))
            else:
                self._slideshow_loading.discard(uuid)

        threading.Thread(
            target=_worker, name=f"slide-{uuid[:8]}", daemon=True,
        ).start()

    def _on_slideshow_loaded(self, uuid: str, imgs: list):
        """6 枚 (or それ以下) の Image を PhotoImage 化してキャッシュ。"""
        try:
            photos = [ImageTk.PhotoImage(i) for i in imgs]
        except Exception as exc:  # noqa: BLE001
            debug(f"slideshow PhotoImage failed {uuid}: {exc}")
            self._slideshow_loading.discard(uuid)
            return
        self._slideshow_cache[uuid] = photos
        # 1 枚目 (poster) をデフォルト表示にも反映
        if photos:
            self._poster_cache[uuid] = photos[0]
            self._apply_poster(uuid, photos[0])
        self._slideshow_loading.discard(uuid)

    def _toggle_grid_fav(self, uuid: str):
        """お気に入りトグル。favorites.json を更新し UI を即時反映。"""
        try:
            new_state = _favorites.toggle_favorite(uuid, self.folder)
        except Exception as exc:  # noqa: BLE001
            self._log(f"❌ お気に入り更新失敗: {exc}")
            return
        if new_state:
            self._favorites_set.add(uuid)
        else:
            self._favorites_set.discard(uuid)
        self._log(f"{'★' if new_state else '☆'} {uuid}")
        # ボタン外観更新
        card = self._grid_cards.get(uuid)
        if card:
            btn = card["fav_btn"]
            try:
                btn.configure(
                    text=("★ お気に入り済" if new_state else "☆ お気に入り"),
                    bg=("#3d3320" if new_state else "#2a2f3a"),
                    fg=("#ffd667" if new_state else "#c8d0dc"),
                )
                # hover 時の戻り色も更新するため、再 bind
                self._make_clickable(
                    btn,
                    on_click=lambda u=uuid: self._toggle_grid_fav(u),
                    hover_bg=("#4a3f28" if new_state else "#3a4250"),
                    normal_bg=("#3d3320" if new_state else "#2a2f3a"),
                )
            except tk.TclError:
                pass
        # フィルタが「お気に入りのみ」なら一覧再構築
        if (self._grid_fav_only_var and self._grid_fav_only_var.get()
                and not new_state):
            self._populate_grid()

    # ─── スキャン ───

    def _run_scan(self):
        """2フェーズスキャン: index.mdを即座に表示 → ファイル情報を非同期で更新。"""
        debug("_run_scan: 開始")
        self._scan_generation = getattr(self, "_scan_generation", 0) + 1
        old_checks = {b: v.get() for b, v in self.check_vars.items()}
        self._old_checks = old_checks
        # converted/ の状態を 1 回だけ scandir で取得 (UUID 数に依存しない)
        self._refresh_converted_state()

        self.check_vars.clear()
        self.url_map.clear()
        self.status_map.clear()
        self.mp4_path_map.clear()
        self.ts_part_path_map.clear()
        self.disabled_checks.clear()
        self.groups.clear()

        # detach済みも含めて全ノードを削除
        debug("_run_scan: ツリー削除開始")
        for uuid in list(self.tree.tag_has("scanning")) + list(self.tree.tag_has("disabled")):
            try:
                self.tree.delete(uuid)
            except tk.TclError:
                pass
        for item in self.tree.get_children():
            self.tree.delete(item)
        # 残存するdetach済みノードも削除（前回フィルターで外れた行）
        if hasattr(self, "entries"):
            for entry in self.entries:
                try:
                    self.tree.delete(entry["uuid"])
                except tk.TclError:
                    pass
        debug("_run_scan: ツリー削除完了")

        # Phase 1: index.md を読み込んで即座に一覧表示
        debug(f"_run_scan: index読み込み開始 (index_file={self.index_file})")
        index_entries = load_index(self.folder, self.index_file)
        debug(f"_run_scan: index読み込み完了 ({len(index_entries)}件)")
        if not index_entries:
            self.status_label.config(text="index.md なし — フォルダスキャン中...")
            self._log("index.md が見つかりません。フォルダ全体をスキャンします。")
            self._run_full_scan(old_checks)
            return

        self.entries = [
            {"uuid": e["uuid"], "url": e["url"]} for e in index_entries
        ]

        for entry in self.entries:
            uuid = entry["uuid"]
            url = entry.get("url", "")
            if url:
                self.url_map[uuid] = url
            var = tk.BooleanVar(value=False)
            self.check_vars[uuid] = var
            self.status_map[uuid] = "🔍 スキャン中"

            self.tree.insert(
                "", tk.END, iid=uuid, text=f"  {uuid}",
                values=("—", "🔍 スキャン中...", "—", "—", "—", "—"),
                tags=("scanning", "disabled"), open=False)

        total = len(self.entries)
        self.status_label.config(text=f"全{total}件 — ファイルスキャン中...")
        self._log(f"index.md 読み込み完了: {total}件。ファイルスキャン開始...")
        debug(f"_run_scan: Phase1完了 ツリー{total}行挿入済み → Phase2スレッド開始")

        # Phase 2: 各UUIDごとにバックグラウンドでスキャン → 1件ずつ更新
        gen = self._scan_generation
        folder_path = Path(self.folder)

        def scan_entries():
            # まずフォルダのファイル一覧を1回だけ取得し、stat()もキャッシュ
            debug("scan_entries: iterdir 開始")
            try:
                all_files = {}
                stat_cache = {}
                for e in folder_path.iterdir():
                    if e.is_file():
                        all_files[e.name] = e
                        t = time.perf_counter()
                        stat_cache[e.name] = e.stat()
                        dt = time.perf_counter() - t
                        if dt > 0.1:
                            debug(f"scan_entries: stat遅延 {e.name} {dt:.3f}s")
            except OSError:
                all_files = {}
                stat_cache = {}
            debug(f"scan_entries: iterdir+stat完了 ({len(all_files)}ファイル)")

            # TSパートをベース名ごとにグルーピング
            debug("scan_entries: TSグルーピング開始")
            ts_groups: dict[str, list] = {}
            for name, entry in all_files.items():
                if not name.endswith(".ts"):
                    continue
                m = PAT_NEW.match(name)
                if m:
                    base = m.group(1)
                    ts_groups.setdefault(base, []).append({
                        "path": str(entry), "name": name,
                        "num": int(m.group(2)),
                        "total": int(m.group(3)),
                        "size": stat_cache[name].st_size,
                        "format": "new",
                    })
                    continue
                m = PAT_OLD.match(name)
                if m:
                    base = m.group(1)
                    ts_groups.setdefault(base, []).append({
                        "path": str(entry), "name": name,
                        "num": int(m.group(2)),
                        "total": None,
                        "size": stat_cache[name].st_size,
                        "format": "old",
                    })

            debug(f"scan_entries: TSグルーピング完了 ({len(ts_groups)}グループ)")

            debug("scan_entries: UUID別スキャン開始")
            for idx, entry_data in enumerate(self.entries):
                if self._scan_generation != gen:
                    debug("scan_entries: 中止 (新スキャン検出)")
                    return
                uuid = entry_data["uuid"]
                t = time.perf_counter()
                info = self._scan_one_uuid(uuid, folder_path, all_files, ts_groups, stat_cache)
                dt = time.perf_counter() - t
                if dt > 0.1:
                    debug(f"scan_entries: [{idx+1}] {uuid[:8]}... {dt:.3f}s (遅い)")
                self.root.after(0, lambda u=uuid, i=info, n=idx+1: self._update_row(u, i, n))
            debug("scan_entries: UUID別スキャン完了")

            # index.mdに無いがフォルダにあるTSグループ
            seen = {e["uuid"] for e in self.entries}
            extra_entries = []
            for base in ts_groups:
                if base not in seen:
                    info = self._scan_one_uuid(base, folder_path, all_files, ts_groups, stat_cache)
                    extra_entries.append({"uuid": base, "url": ""})
                    self.root.after(0, lambda b=base, i=info: self._add_extra_row(b, i))

            # index.mdにもts_groupsにも無い単体TSファイル
            for name in all_files:
                if not name.endswith(".ts"):
                    continue
                if PAT_NEW.match(name) or PAT_OLD.match(name):
                    continue
                base = name[:-3]  # .ts を除去
                if base in seen or base in ts_groups:
                    continue
                # MP4が既にあれば対象外
                if f"{base}.mp4" in all_files or f"{base}_1.mp4" in all_files:
                    continue
                info = self._scan_one_uuid(base, folder_path, all_files, ts_groups, stat_cache)
                extra_entries.append({"uuid": base, "url": ""})
                self.root.after(0, lambda b=base, i=info: self._add_extra_row(b, i))

            if extra_entries:
                self.root.after(0, lambda ee=extra_entries: self._finish_extra(ee))

            self.root.after(0, lambda: self._finish_scan())
            debug("scan_entries: 全完了")

        threading.Thread(target=scan_entries, daemon=True).start()

    def _scan_one_uuid(
        self, uuid: str, folder_path: Path,
        all_files: dict, ts_groups: dict,
        stat_cache: dict | None = None,
    ) -> dict:
        """1つのUUIDに対してファイル情報を収集する。"""
        info: dict = {
            "parts": [], "total": None, "format": "none",
            "total_size": 0, "part_count": 0,
            "complete": True, "missing": [], "expected_count": 0,
            "oldest_mtime": 0,
            "merged_mp4": {"exists": False, "size": 0, "path": ""},
            "merged_ts": {"exists": False, "size": 0, "path": ""},
            "split_mp4s": [],
        }

        # TSパート
        if uuid in ts_groups:
            raw_parts = ts_groups[uuid]
            raw_parts.sort(key=lambda p: p["num"])
            fmt = raw_parts[0]["format"]
            total_hint = raw_parts[0].get("total")

            parts = []
            for rp in raw_parts:
                parts.append({
                    "path": rp["path"], "name": rp["name"],
                    "num": rp["num"], "size": rp["size"],
                })
            info["parts"] = parts
            info["format"] = fmt
            info["total"] = total_hint
            info["total_size"] = sum(p["size"] for p in parts)
            info["part_count"] = len(parts)

            if fmt == "new" and total_hint is not None:
                expected = set(range(1, total_hint + 1))
                actual = {p["num"] for p in parts}
                info["complete"] = actual == expected
                info["missing"] = sorted(expected - actual)
                info["expected_count"] = total_hint
            else:
                nums = [p["num"] for p in parts]
                if nums:
                    expected = set(range(min(nums), max(nums) + 1))
                    info["complete"] = set(nums) == expected
                    info["missing"] = sorted(expected - set(nums))
                    info["expected_count"] = len(expected)

        # 結合済みMP4
        mp4_name = f"{uuid}.mp4"
        if mp4_name in all_files:
            e = all_files[mp4_name]
            sz = stat_cache[mp4_name].st_size if stat_cache and mp4_name in stat_cache else e.stat().st_size
            info["merged_mp4"] = {
                "exists": True,
                "size": sz,
                "path": str(e),
            }

        # 単体TS (パート番号なし: uuid.ts)
        ts_name = f"{uuid}.ts"
        has_mp4 = info["merged_mp4"]["exists"]
        if ts_name in all_files:
            e = all_files[ts_name]
            sz = stat_cache[ts_name].st_size if stat_cache and ts_name in stat_cache else e.stat().st_size

            if info["part_count"] == 0 and not has_mp4 and not info.get("split_mp4s"):
                # パートなし・MP4なし → 未変換の単体TSとして扱う
                info["parts"] = [{
                    "path": str(e), "name": ts_name,
                    "num": 1, "size": sz,
                }]
                info["format"] = "single"
                info["total"] = 1
                info["total_size"] = sz
                info["part_count"] = 1
                info["complete"] = True
                info["missing"] = []
                info["expected_count"] = 1
                info["merged_ts"] = {"exists": False, "size": 0, "path": ""}
            else:
                # パートあり or MP4あり → 結合済みTSとして扱う
                info["merged_ts"] = {
                    "exists": True,
                    "size": sz,
                    "path": str(e),
                }

        # 分割MP4
        for i in range(1, 10):
            sp_name = f"{uuid}_{i}.mp4"
            if sp_name in all_files:
                e = all_files[sp_name]
                sz = stat_cache[sp_name].st_size if stat_cache and sp_name in stat_cache else e.stat().st_size
                info["split_mp4s"].append({
                    "path": str(e), "name": sp_name,
                    "num": i, "size": sz,
                })
            else:
                break

        return info

    # ─── HLS 変換状態とサムネ ───

    def _refresh_converted_state(self):
        """converted/ を 1 回 scandir してマーカー / 完了情報を一括取得する。

        Drive FUSE 等で個別 stat が遅い環境では、UUID ごとに 7-9 回 stat する
        旧実装より大幅に高速。スキャン開始時 (1 回) だけ呼べば十分。
        """
        debug("_refresh_converted_state: 開始")
        t0 = time.perf_counter()
        from hls_video.config import converted_dir_name

        # 1) converted/ を listdir のみで取得 (Drive FUSE で stat 不要)
        converted_root = Path(self.folder) / converted_dir_name()
        SKIP_NAMES = {"hls-index.json", ".hls-index.json", ".index.json"}
        present: set[str] = set()
        try:
            for name in os.listdir(converted_root):
                if name.startswith("."):
                    continue
                if name in SKIP_NAMES:
                    continue
                present.add(name)
        except OSError as exc:
            debug(f"_refresh_converted_state: listdir エラー: {exc}")

        self._converted_dirs = present
        # 暫定: index ロード前は全部「未確定」(背景ロード完了後に更新)
        self._completed_set = set()
        self._suspicious_dirs = set(present)
        self._converting_dirs = set()

        debug(
            f"_refresh_converted_state: listdir 完了 "
            f"({(time.perf_counter()-t0)*1000:.1f}ms) "
            f"present={len(present)}"
        )

        # 2) index ロードは背景スレッドで (Drive FUSE では初回ダウンロード待ちで
        #    数十秒〜数分かかるため、GUI スレッドをブロックしない)
        self._start_background_index_load(present)

    def _start_background_index_load(self, present: set[str]):
        """インデックスを別スレッドで読み、完了したら _on_index_loaded で反映する。"""
        gen = self._scan_generation

        def _worker():
            from hls_video import converted_index as _ci
            t0 = time.perf_counter()
            try:
                idx = _ci.load(self.folder)
                completed = set((idx.get("completed") or {}).keys())
            except Exception as exc:  # noqa: BLE001
                debug(f"index load worker エラー: {exc}")
                completed = set()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self.root.after(
                0,
                lambda c=completed, p=present, g=gen, e=elapsed_ms:
                    self._on_index_loaded(c, p, g, e),
            )

        threading.Thread(target=_worker, name="hls-index-loader", daemon=True).start()

    def _on_index_loaded(
        self, completed: set[str], present: set[str],
        gen: int, elapsed_ms: float,
    ):
        """背景ロード完了 → 各行の HLS 状態を再評価して必要な行だけ更新。"""
        if gen != self._scan_generation:
            return  # 古いスキャンの結果
        self._completed_set = completed
        self._suspicious_dirs = present - completed
        debug(
            f"index loaded ({elapsed_ms:.0f}ms): "
            f"indexed={len(completed)}, suspicious={len(self._suspicious_dirs)}"
        )

        # ツリーで HLS 列を持つ全行を再描画 (ステータスが変わる可能性のある行のみ)
        try:
            updated = 0
            for uuid in list(self.tree.get_children()):
                if uuid not in self._converted_dirs:
                    continue
                # 値配列の HLS 列だけ書き換え (再描画範囲を最小化)
                vals = list(self.tree.item(uuid, "values"))
                if len(vals) < 6:
                    continue
                state, label = self._hls_state(uuid)
                if vals[2] != label:
                    vals[2] = label
                    self.tree.item(uuid, values=tuple(vals))
                    self.hls_status_map[uuid] = state
                    # 完了に変わったらサムネを背景でロード
                    if state == "done" and uuid not in self._thumb_cache:
                        self._enqueue_thumb_load(uuid)
                    updated += 1
        except tk.TclError:
            return
        self._log(
            f"📑 インデックス読み込み完了: {len(completed)} 件 "
            f"({elapsed_ms/1000:.1f}s){' / 行更新: ' + str(updated) if updated else ''}"
        )

    def _hls_state(self, uuid: str) -> tuple[str, str]:
        """(state_key, label) を返す。 O(1) — 個別 stat なし。

        判定は **インデックス + scandir 結果** のみで決まる:
          - converted/<uuid>/ が無い              → "📼 HLS未"
          - インデックスに登録あり                → "🎞 HLS済"  (確定)
          - dir はあるが index 未登録            → "⏳ HLS未確定" (中断 or 未 rebuild)

        Drive FUSE 環境では 1 動画あたりのファイル stat を完全に避けるため、
        マーカーファイル `.converting` の存在チェックは行わない。厳密な判定が
        必要な場合は `hls-convert --rebuild-index` で index を最新化してから開く。
        """
        if uuid not in self._converted_dirs:
            return "none", "📼 HLS未"
        if uuid in self._completed_set:
            return "done", "🎞 HLS済"
        return "converting", "⏳ HLS未確定"

    def _thumb_for(self, uuid: str) -> object | None:
        """既にキャッシュされたサムネ画像を返す (バックグラウンド生成は別途)。"""
        if not _PIL_AVAILABLE:
            return None
        return self._thumb_cache.get(uuid)

    def _enqueue_thumb_load(self, uuid: str):
        """サムネを別スレッドで読み込み、完了時に該当行へ反映する。

        UI スレッドでの PIL ロードは Drive FUSE 上で 100ms 級になりブロックする。
        background thread でバイト読み + リサイズし、最後の `ImageTk.PhotoImage`
        とツリー更新だけ main thread (after) で行う。
        """
        if not _PIL_AVAILABLE:
            return
        if uuid in self._thumb_cache:
            return
        # 候補ファイル: poster.png 優先、無ければ thumb_50.jpg
        out_dir = output_dir_for(uuid, Path(self.folder))
        poster = out_dir / "thumbs" / "poster.png"
        thumb50 = out_dir / "thumbs" / "thumb_50.jpg"

        gen = self._scan_generation

        def _worker():
            # 重い IO + 縮小はここで (worker thread)
            src = poster if poster.is_file() else (thumb50 if thumb50.is_file() else None)
            if src is None:
                return
            try:
                img = Image.open(src)
                img.thumbnail((80, 45), Image.LANCZOS)
                # ImageTk.PhotoImage は Tcl の操作が入るので main thread で
                self.root.after(0, lambda i=img, u=uuid, g=gen: self._apply_thumb(u, i, g))
            except Exception as exc:  # noqa: BLE001
                debug(f"thumb worker failed {uuid}: {exc}")

        threading.Thread(target=_worker, name=f"thumb-{uuid[:8]}", daemon=True).start()

    def _apply_thumb(self, uuid: str, img, gen: int):
        """worker thread から渡された PIL.Image を Tk 画像化して該当行へ反映 (main thread)。"""
        if gen != self._scan_generation:
            return  # 古いスキャンの結果
        if uuid in self._thumb_cache:
            return
        try:
            photo = ImageTk.PhotoImage(img)
        except Exception as exc:  # noqa: BLE001
            debug(f"ImageTk failed {uuid}: {exc}")
            return
        self._thumb_cache[uuid] = photo
        # ツリーが該当行を持っていれば画像を貼る
        try:
            if self.tree.exists(uuid):
                self.tree.item(uuid, image=photo)
        except tk.TclError:
            pass

    def _update_row(self, uuid: str, info: dict, progress: int):
        """スキャン結果で1行を更新する (メインスレッド)。"""
        self.groups[uuid] = info
        old_checks = self._old_checks

        # 既存の子ノードを削除
        for child in self.tree.get_children(uuid):
            self.tree.delete(child)

        has_mp4 = info["merged_mp4"]["exists"]
        has_ts = info["merged_ts"]["exists"]
        split_mp4s = info.get("split_mp4s", [])
        has_split_mp4 = len(split_mp4s) > 0
        has_any_mp4 = has_mp4 or has_split_mp4
        is_complete = info.get("complete", False)

        if has_any_mp4:
            has_remaining_ts = info["part_count"] > 0 or has_ts
            # 分割MP4の完全性チェック (ts_merge_colab.py は常に2分割)
            split_complete = True
            if has_split_mp4:
                split_nums = sorted(s["num"] for s in split_mp4s)
                split_complete = split_nums == [1, 2]
            status = "✅ MP4済(ts有)" if has_remaining_ts else "✅ MP4済"
            if has_split_mp4:
                if not split_complete:
                    status = f"⚠ MP4不完全({len(split_mp4s)}/2分割)"
                    if has_remaining_ts:
                        status = f"⚠ MP4不完全({len(split_mp4s)}/2分割,ts有)"
                else:
                    status = f"✅ MP4済({len(split_mp4s)}分割)"
                    if has_remaining_ts:
                        status = f"✅ MP4済({len(split_mp4s)}分割,ts有)"
            tag = "merged_done"
            filter_cat = "🗑 MP4済(TS有)" if has_remaining_ts else "✅ MP4済"
            if has_mp4:
                self.mp4_path_map[uuid] = info["merged_mp4"]["path"]
            elif split_mp4s:
                self.mp4_path_map[uuid] = split_mp4s[0]["path"]
            if info["part_count"] == 0 and not has_ts:
                self.disabled_checks.add(uuid)
        elif has_ts:
            status = "✅ TS済"
            tag, filter_cat = "merged_done", "✅ TS済"
        elif info["part_count"] == 0:
            status = "📥 未DL"
            tag, filter_cat = "no_parts", "📥 未DL"
            self.disabled_checks.add(uuid)
        elif not is_complete and info["part_count"] > 0:
            expected = info.get("expected_count", 0)
            actual = info.get("part_count", 0)
            status = f"⚠ 不完全 {actual}/{expected}"
            tag, filter_cat = "incomplete", "⚠ 不完全"
        else:
            status = "⏳ 未結合"
            tag, filter_cat = "pending", "⏳ 未結合"

        self.status_map[uuid] = filter_cat

        # 結合済み情報
        merged_parts = []
        if has_mp4:
            merged_parts.append(f".mp4 ({format_size(info['merged_mp4']['size'])})")
        if split_mp4s:
            total_split = sum(s["size"] for s in split_mp4s)
            merged_parts.append(f"_{1}-{len(split_mp4s)}.mp4 ({format_size(total_split)})")
        if has_ts:
            merged_parts.append(f".ts ({format_size(info['merged_ts']['size'])})")
        url = self.url_map.get(uuid, "")
        if filter_cat == "📥 未DL" and url:
            merged_info = url
        else:
            merged_info = " / ".join(merged_parts) if merged_parts else "—"

        parts_str = f"{info['part_count']} パート" if info["part_count"] > 0 else "—"
        size_str = format_size(info["total_size"]) if info["total_size"] > 0 else "—"

        is_disabled = uuid in self.disabled_checks
        if is_disabled:
            self.check_vars[uuid].set(False)
            check_mark, check_tag = "—", "disabled"
        else:
            default = (has_any_mp4 and split_complete and (info["part_count"] > 0 or has_ts))
            self.check_vars[uuid].set(old_checks.get(uuid, default))
            check_mark = "✅" if self.check_vars[uuid].get() else "⬜"
            check_tag = "checked" if self.check_vars[uuid].get() else "unchecked"

        # HLS 変換ステータス + サムネ画像
        hls_state, hls_label = self._hls_state(uuid)
        self.hls_status_map[uuid] = hls_state

        item_kwargs = {
            "text": f"  {uuid}",
            "values": (check_mark, status, hls_label, parts_str, size_str, merged_info),
            "tags": (tag, check_tag),
        }
        cached_thumb = self._thumb_for(uuid)
        if cached_thumb is not None:
            item_kwargs["image"] = cached_thumb
        self.tree.item(uuid, **item_kwargs)

        # サムネ未キャッシュ + HLS 完了状態 → 別スレッドで非同期ロード
        if cached_thumb is None and hls_state == "done":
            self._enqueue_thumb_load(uuid)

        # 子ノード: MP4
        if has_mp4:
            mp4_name = Path(info["merged_mp4"]["path"]).name
            child_id = f"{uuid}__mp4"
            self.tree.insert(
                uuid, tk.END, iid=child_id,
                text=f"    📹 {mp4_name}",
                values=("", "", "", format_size(info["merged_mp4"]["size"]), ""),
                tags=("child_mp4",))
            self.mp4_path_map[child_id] = info["merged_mp4"]["path"]

        for smp4 in split_mp4s:
            child_id = f"{uuid}__mp4_{smp4['num']}"
            self.tree.insert(
                uuid, tk.END, iid=child_id,
                text=f"    📹 {smp4['name']}",
                values=("", "", "", format_size(smp4["size"]), ""),
                tags=("child_mp4",))
            self.mp4_path_map[child_id] = smp4["path"]

        # 子ノード: TSパート
        for part in info["parts"]:
            child_id = f"{uuid}__ts_{part['num']}_{part['name']}"
            self.tree.insert(
                uuid, tk.END, iid=child_id,
                text=f"    📄 {part['name']}",
                values=("", "", "", format_size(part["size"]), ""),
                tags=("child_ts",))
            self.ts_part_path_map[child_id] = part["path"]

        total = len(self.entries)
        self.status_label.config(text=f"全{total}件 — スキャン中... ({progress}/{total})")

    def _add_extra_row(self, base: str, info: dict):
        """index.mdに無いがフォルダにあるグループを追加。"""
        self.entries.append({"uuid": base, "url": ""})
        var = tk.BooleanVar(value=False)
        self.check_vars[base] = var
        self.tree.insert(
            "", tk.END, iid=base, text=f"  {base}",
            values=("—", "🔍 スキャン中...", "—", "—", "—", "—"),
            tags=("scanning", "disabled"), open=False)
        self._update_row(base, info, len(self.entries))

    def _finish_extra(self, extra_entries: list[dict]):
        """追加エントリをself.entriesに反映。"""
        pass  # _add_extra_row で既に追加済み

    def _finish_scan(self):
        """スキャン完了時のサマリー表示。"""
        self._last_scan_at = datetime.now().isoformat()
        counts = {"mp4": 0, "mp4_ts": 0, "ts": 0,
                  "pending": 0, "incomplete": 0, "no_dl": 0}
        cat_to_key = {
            "✅ MP4済": "mp4", "🗑 MP4済(TS有)": "mp4_ts", "✅ TS済": "ts",
            "⏳ 未結合": "pending", "⚠ 不完全": "incomplete",
            "📥 未DL": "no_dl",
        }
        for cat in self.status_map.values():
            key = cat_to_key.get(cat)
            if key:
                counts[key] += 1

        self._apply_filter()

        total = len(self.entries)
        now = datetime.now().strftime("%H:%M:%S")
        self.status_label.config(text=(
            f"全{total}件"
            f" | MP4済: {counts['mp4']}"
            f" / MP4済(TS有): {counts['mp4_ts']}"
            f" / TS済: {counts['ts']}"
            f" / 未結合: {counts['pending']}"
            f" / 不完全: {counts['incomplete']}"
            f" / 未DL: {counts['no_dl']}"
            f" | {now}"
        ))
        self._log(
            f"スキャン完了: 全{total}件"
            f" (MP4済: {counts['mp4']}, MP4済(TS有): {counts['mp4_ts']},"
            f" TS済: {counts['ts']},"
            f" 未結合: {counts['pending']}, 不完全: {counts['incomplete']},"
            f" 未DL: {counts['no_dl']})"
        )

    def _run_full_scan(self, old_checks: dict):
        """index.mdがない場合のフォールバック: 従来通りの一括スキャン。"""
        gen = self._scan_generation

        def scan():
            groups = scan_folder(self.folder)
            if self._scan_generation != gen:
                return
            entries = [{"uuid": b, "url": ""} for b in sorted(groups)]
            self.root.after(0, lambda: self._on_full_scan_done(entries, groups, old_checks))

        threading.Thread(target=scan, daemon=True).start()

    def _on_full_scan_done(self, entries: list[dict], groups: dict, old_checks: dict):
        """index.mdなしフォールバックの完了処理。"""
        self.entries = entries
        self._old_checks = old_checks
        for entry in entries:
            uuid = entry["uuid"]
            var = tk.BooleanVar(value=False)
            self.check_vars[uuid] = var
            self.status_map[uuid] = "🔍 スキャン中"
            self.tree.insert(
                "", tk.END, iid=uuid, text=f"  {uuid}",
                values=("—", "🔍 スキャン中...", "—", "—", "—", "—"),
                tags=("scanning", "disabled"), open=False)

        for idx, entry in enumerate(entries):
            uuid = entry["uuid"]
            info = groups[uuid]
            self._update_row(uuid, info, idx + 1)

        self._finish_scan()

    # ─── フィルター ───

    def _apply_filter(self):
        active_cats = {cat for cat, var in self.filter_vars.items() if var.get()}
        all_items = list(self.tree.get_children())
        for item in all_items:
            self.tree.detach(item)

        for entry in self.entries:
            uuid = entry["uuid"]
            cat = self.status_map.get(uuid, "")
            if cat in active_cats:
                try:
                    self.tree.reattach(uuid, "", tk.END)
                except tk.TclError:
                    pass

    # ─── ツリー操作 ───

    def _on_tree_click(self, event):
        col = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)
        if not item or item not in self.check_vars or col != "#1":
            return
        if item in self.disabled_checks:
            return
        var = self.check_vars[item]
        var.set(not var.get())
        self._update_row_display(item)

    def _on_tree_double_click(self, event):
        """行をダブルクリック → converted/<uuid>/ があれば再生試行。"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        parent = self.tree.parent(item)
        base = parent if parent else item
        if base not in self.check_vars:
            return
        if base in self._converted_dirs:
            self._play_uuid(base)

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)

        # TSパート子ノードならパート用メニューを表示
        if item in self.ts_part_path_map:
            self.ts_part_context_menu.post(event.x_root, event.y_root)
            return

        base_item = self.tree.parent(item) or item

        has_url = base_item in self.url_map
        self.context_menu.entryconfigure(
            "URLをコピー", state=tk.NORMAL if has_url else tk.DISABLED)
        self.context_menu.entryconfigure(
            "ブラウザで開く", state=tk.NORMAL if has_url else tk.DISABLED)
        self.context_menu.entryconfigure(
            "indexから削除", state=tk.NORMAL if has_url else tk.DISABLED)
        self.context_menu.post(event.x_root, event.y_root)

    def _update_row_display(self, base: str):
        var = self.check_vars.get(base)
        if var is None:
            return

        if base in self.disabled_checks:
            check_mark, check_tag = "—", "disabled"
        else:
            checked = var.get()
            check_mark = "✅" if checked else "⬜"
            check_tag = "checked" if checked else "unchecked"

        info = self.groups.get(base)
        if info:
            has_mp4 = info["merged_mp4"]["exists"]
            has_ts = info["merged_ts"]["exists"]
            has_split_mp4 = len(info.get("split_mp4s", [])) > 0
            if has_mp4 or has_ts or has_split_mp4:
                base_tag = "merged_done"
            elif not info.get("complete", False) and info.get("part_count", 0) > 0:
                base_tag = "incomplete"
            else:
                base_tag = "pending"
        else:
            base_tag = "no_parts"

        vals = list(self.tree.item(base, "values"))
        vals[0] = check_mark
        self.tree.item(base, values=vals, tags=(base_tag, check_tag))

    def _select_all(self):
        for base, var in self.check_vars.items():
            if base not in self.disabled_checks:
                var.set(True)
                self._update_row_display(base)

    def _deselect_all(self):
        for base, var in self.check_vars.items():
            if base not in self.disabled_checks:
                var.set(False)
                self._update_row_display(base)

    def _get_current_item(self) -> str | None:
        """選択中のアイテムIDをそのまま返す。"""
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _get_current_base(self) -> str | None:
        """選択中アイテムの親ベースIDを返す。"""
        item = self._get_current_item()
        if not item:
            return None
        parent = self.tree.parent(item)
        base = parent if parent else item
        return base if base in self.check_vars else None

    # ─── アクション ───

    def _delete_ts_parts(self):
        """チェック済みの「MP4済(ts有)」行のTSパートファイルを削除する。"""
        targets = []
        for base, var in self.check_vars.items():
            if not var.get() or base in self.disabled_checks:
                continue
            info = self.groups.get(base)
            if not info:
                continue
            has_mp4 = info["merged_mp4"]["exists"] or bool(info.get("split_mp4s"))
            has_ts_files = info.get("part_count", 0) > 0 or info["merged_ts"]["exists"]
            if not has_mp4 or not has_ts_files:
                continue
            targets.append(base)

        if not targets:
            messagebox.showinfo(
                "情報",
                "削除対象がありません。\n"
                "「✅ MP4済(ts有)」の行をチェックしてください。")
            return

        # 削除するファイル数とサイズを計算
        total_files = 0
        total_size = 0
        for base in targets:
            info = self.groups[base]
            total_files += info["part_count"]
            total_size += info["total_size"]
            if info["merged_ts"]["exists"]:
                total_files += 1
                total_size += info["merged_ts"]["size"]

        # 分割MP4が不完全なグループを検出
        # ts_merge_colab.py では20GB超を常に _1.mp4 + _2.mp4 の2分割で出力する
        EXPECTED_SPLIT_COUNT = 2
        incomplete_split = []
        for base in targets:
            info = self.groups[base]
            split_mp4s = info.get("split_mp4s", [])
            if not split_mp4s:
                continue
            nums = sorted(s["num"] for s in split_mp4s)
            expected = list(range(1, EXPECTED_SPLIT_COUNT + 1))
            if nums != expected:
                missing = sorted(set(expected) - set(nums))
                incomplete_split.append(
                    f"  {base[:12]}... (_{', _'.join(str(m) for m in missing)}.mp4 が不足)")

        warn_msg = ""
        if incomplete_split:
            warn_msg = (
                "\n\n⚠️ 以下のグループは分割MP4が揃っていません:\n"
                + "\n".join(incomplete_split)
                + "\n\nTSを削除すると再変換できなくなります。"
            )

        msg = (
            f"{len(targets)}グループの TSファイルを削除しますか？\n\n"
            f"削除ファイル数: {total_files}ファイル\n"
            f"削除サイズ: {format_size(total_size)}\n\n"
            f"※ MP4ファイルは残ります。この操作は元に戻せません。"
            + warn_msg
        )
        if not messagebox.askyesno("TS削除", msg):
            return

        deleted = 0
        errors = 0
        for base in targets:
            info = self.groups[base]
            # 分割TSパート削除
            for part in info["parts"]:
                try:
                    Path(part["path"]).unlink()
                    deleted += 1
                except OSError as e:
                    self._log(f"❌ 削除失敗: {part['name']} - {e}")
                    errors += 1
            # 単体TS (merged_ts) 削除
            if info["merged_ts"]["exists"]:
                try:
                    Path(info["merged_ts"]["path"]).unlink()
                    deleted += 1
                except OSError as e:
                    self._log(f"❌ 削除失敗: {Path(info['merged_ts']['path']).name} - {e}")
                    errors += 1
            del_count = info["part_count"] + (1 if info["merged_ts"]["exists"] else 0)
            self._log(f"🗑 TS削除: {base} ({del_count}ファイル)")

        self._log(
            f"--- 削除完了: {deleted}ファイル削除"
            + (f", {errors}件エラー" if errors else "")
            + f", {format_size(total_size)} 解放 ---"
        )
        self._run_scan()

    def _delete_single_ts_part(self):
        """右クリックで選択した1つのTSパートファイルを削除する。"""
        sel = self.tree.selection()
        if not sel:
            return
        item = sel[0]
        path_str = self.ts_part_path_map.get(item)
        if not path_str:
            return

        path = Path(path_str)
        if not path.exists():
            messagebox.showwarning("警告", f"ファイルが見つかりません:\n{path.name}")
            self._run_scan()
            return

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        msg = (
            f"以下のTSパートファイルを削除しますか？\n\n"
            f"ファイル: {path.name}\n"
            f"サイズ: {format_size(size)}\n\n"
            f"※ この操作は元に戻せません。\n"
            f"   再ダウンロードで復元できます。"
        )
        if not messagebox.askyesno("TSパート削除", msg):
            return

        try:
            path.unlink()
            self._log(f"🗑 TSパート削除: {path.name} ({format_size(size)})")
        except OSError as e:
            self._log(f"❌ 削除失敗: {path.name} - {e}")
            messagebox.showerror("エラー", f"削除に失敗しました:\n{e}")
            return

        self._run_scan()

    def _remove_from_index_single(self):
        """右クリックで選択した1行をindexから削除する。"""
        base = self._get_current_base()
        if not base or base not in self.url_map:
            messagebox.showinfo("情報", "indexに登録されていない行です。")
            return

        url = self.url_map[base]
        if not messagebox.askyesno(
            "indexから削除",
            f"以下をindex.mdから削除しますか？\n\n{base}\n{url}",
        ):
            return

        removed = remove_from_index(self.folder, {base}, self.index_file)
        if removed > 0:
            self._log(f"📝 indexから削除: {base}")
            self._run_scan()
        else:
            self._log(f"⚠ indexに該当行が見つかりません: {base}")

    def _remove_from_index_checked(self):
        """チェック済みの行をindexから一括削除する。"""
        targets = [
            base for base, var in self.check_vars.items()
            if var.get() and base not in self.disabled_checks
            and base in self.url_map
        ]

        if not targets:
            messagebox.showinfo(
                "情報",
                "削除対象がありません。\nindexに登録されている行をチェックしてください。")
            return

        msg = (
            f"{len(targets)}件をindex.mdから削除しますか？\n\n"
            + "\n".join(f"  {t[:12]}..." for t in targets[:10])
        )
        if len(targets) > 10:
            msg += f"\n  ... 他{len(targets) - 10}件"
        msg += "\n\n※ ファイルは削除されません。index.mdの行のみ削除します。"

        if not messagebox.askyesno("indexから削除", msg):
            return

        removed = remove_from_index(self.folder, set(targets), self.index_file)
        self._log(f"📝 indexから{removed}件削除")
        self._run_scan()

    def _add_to_index_inline(self):
        """インライン入力エリアからURLをindex.mdの先頭に追加する。"""
        raw = self.add_text.get("1.0", tk.END).strip()
        if not raw:
            self.add_result_label.config(text="URLを貼り付けてください", foreground="orange")
            return

        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        if not urls:
            self.add_result_label.config(text="URLを貼り付けてください", foreground="orange")
            return

        valid = []
        invalid = 0
        for url in urls:
            if PAT_INDEX_URL.search(url):
                valid.append(url)
            else:
                invalid += 1

        if not valid:
            self.add_result_label.config(
                text=f"有効なURLがありません ({invalid}件無効)", foreground="red")
            return

        added, skipped = add_to_index(self.folder, valid, self.index_file)
        parts = []
        if added:
            parts.append(f"{added}件追加")
        if skipped:
            parts.append(f"{skipped}件重複スキップ")
        if invalid:
            parts.append(f"{invalid}件無効")
        msg = "、".join(parts)
        self._log(f"📝 index追加: {msg}")

        if added > 0:
            self.add_text.delete("1.0", tk.END)
            self.add_result_label.config(text=f"✅ {msg}", foreground="green")
            self._run_scan()
        else:
            self.add_result_label.config(text=msg, foreground="orange")

    def _open_folder(self):
        """対象ディレクトリをFinderで開く。"""
        try:
            subprocess.Popen(["open", self.folder])
            self._log(f"Finderで開く: {self.folder}")
        except Exception as e:
            self._log(f"❌ Finderで開けません: {e}")

    def _copy_url(self):
        base = self._get_current_base()
        if not base:
            return
        url = self.url_map.get(base, "")
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self._log(f"URLコピー: {url}")

    def _open_url(self):
        base = self._get_current_base()
        if not base:
            return
        url = self.url_map.get(base, "")
        if url:
            webbrowser.open(url)
            self._log(f"ブラウザで開く: {url}")

    # ─── Colabコマンド生成 ───

    def _copy_colab_cmd(self):
        """チェック済みの結合対象からColab用コマンドを生成しコピーする。"""
        selected = [
            base for base, var in self.check_vars.items()
            if var.get() and base not in self.disabled_checks
            and base in self.groups and self.groups[base].get("part_count", 0) > 0
        ]

        no_dl = [
            uuid for uuid in self.status_map
            if self.status_map[uuid] == "📥 未DL"
        ]

        if not selected and not no_dl:
            messagebox.showinfo(
                "情報", "コマンド生成対象がありません。\n結合対象をチェックしてください。")
            return

        lines = []

        if no_dl:
            lines.append(f"# 未ダウンロード: {len(no_dl)}件")
            for uuid in no_dl:
                url = self.url_map.get(uuid, "")
                lines.append(f"# {url}")
            lines.append("")

        if selected:
            if len(selected) <= 5:
                for base in selected:
                    lines.append(
                        f"!python ts_merge_colab.py"
                        f" --filter {base} --force --delete -w 1 &")
                lines.append("wait")
            else:
                lines.append(
                    f"!python ts_merge_colab.py --force --delete -w 4")

            lines.append("")
            lines.append(f"# 対象: {len(selected)}件")
            for base in selected:
                info = self.groups.get(base, {})
                parts = info.get("part_count", 0)
                size = format_size(info.get("total_size", 0))
                complete = "完全" if info.get("complete", False) else "不完全"
                lines.append(f"#   {base} ({parts}パート, {size}, {complete})")

        cmd_text = "\n".join(lines)

        self.root.clipboard_clear()
        self.root.clipboard_append(cmd_text)
        self._log(f"Colabコマンドをコピー ({len(selected)}件の結合対象)")

        preview = cmd_text if len(cmd_text) <= 500 else cmd_text[:500] + "\n..."
        messagebox.showinfo(
            "Colabコマンド (コピー済み)",
            f"クリップボードにコピーしました:\n\n{preview}")

    # ─── プレイヤー (FastAPI) 起動 + 再生 ───

    def _toggle_player_server(self):
        """プレイヤーサーバの起動/停止トグル。"""
        if self._player_running:
            self._stop_player_server()
        else:
            self._start_player_server()

    def _start_player_server(self) -> bool:
        """同プロセスで FastAPI を起動する (daemon thread)。

        port が listening になるまで最大 10 秒待つ。失敗時は messagebox で通知。
        Returns: True なら起動成功、False なら失敗。
        """
        if self._player_running:
            return True
        try:
            import uvicorn
            from app.main import build_app
            from hls_video.library_settings import set_library_root
        except Exception as exc:  # noqa: BLE001
            import traceback
            tb = traceback.format_exc()
            self._log(f"❌ プレイヤー起動失敗 (依存不足?): {exc}")
            messagebox.showerror(
                "プレイヤー起動失敗",
                f"FastAPI / Gradio が読み込めませんでした:\n{exc}\n\n"
                "pipx で再インストール:\n"
                "  pipx install --force \"<repo>[gui,app]\"\n\n"
                f"詳細:\n{tb[-500:]}",
            )
            return False

        # GUI のフォルダをライブラリルートとして登録
        try:
            set_library_root(self.folder)
        except Exception as exc:  # noqa: BLE001
            self._log(f"⚠ set_library_root 失敗: {exc}")

        try:
            fapi = build_app()
        except Exception as exc:  # noqa: BLE001
            import traceback
            tb = traceback.format_exc()
            self._log(f"❌ build_app 失敗: {exc}")
            messagebox.showerror(
                "プレイヤー起動失敗 (build_app)",
                f"{exc}\n\n詳細:\n{tb[-500:]}",
            )
            return False

        config = uvicorn.Config(
            fapi, host="127.0.0.1", port=self.player_port,
            log_level="warning",
        )
        self._player_server = uvicorn.Server(config)

        # クラッシュ情報を main thread に届けるための共有変数
        crash_info: dict = {}

        def _run():
            try:
                self._player_server.run()
            except BaseException as exc:  # noqa: BLE001
                import traceback
                crash_info["error"] = str(exc)
                crash_info["traceback"] = traceback.format_exc()
                debug(f"player server crashed: {exc}")
            finally:
                self._player_running = False
                self.root.after(0, self._refresh_player_btn)
                # 起動後にクラッシュした場合は messagebox で通知
                if crash_info and crash_info.get("notify"):
                    self.root.after(
                        0,
                        lambda c=dict(crash_info): self._show_player_crash(c),
                    )

        self._player_thread = threading.Thread(
            target=_run, name="hls-player-uvicorn", daemon=True)
        self._player_thread.start()
        self._player_running = True

        # uvicorn が port 7860 を listen するまで polling で待つ (最大 10 秒)
        import socket
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not self._player_thread.is_alive():
                # スレッドが死んだ → クラッシュ
                err = crash_info.get("error", "(unknown)")
                tb = crash_info.get("traceback", "")
                self._player_running = False
                self._log(f"❌ プレイヤーサーバが起動直後にクラッシュ: {err}")
                messagebox.showerror(
                    "プレイヤー起動失敗 (uvicorn)",
                    f"{err}\n\n詳細:\n{tb[-800:]}",
                )
                return False
            try:
                with socket.create_connection(("127.0.0.1", self.player_port), timeout=0.3):
                    self._log(
                        f"🎬 プレイヤー起動: http://127.0.0.1:{self.player_port}/  "
                        f"(ライブラリ: {self.folder})"
                    )
                    self._refresh_player_btn()
                    # 起動成功後のクラッシュは messagebox で通知させる
                    crash_info["notify"] = True
                    return True
            except OSError:
                time.sleep(0.2)

        # タイムアウト
        self._log(
            f"❌ プレイヤーサーバ起動タイムアウト (port {self.player_port} が "
            "10 秒経っても listening になりません)"
        )
        messagebox.showerror(
            "プレイヤー起動タイムアウト",
            f"port {self.player_port} が 10 秒経っても応答しません。\n"
            "他のプロセスがポートを使用しているか、ビルドが詰まっている可能性があります。\n"
            f"`lsof -i :{self.player_port}` で確認してください。",
        )
        return False

    def _show_player_crash(self, info: dict):
        """プレイヤースレッドが起動後にクラッシュした時の通知。"""
        err = info.get("error", "(unknown)")
        tb = info.get("traceback", "")
        messagebox.showerror(
            "プレイヤーサーバが停止しました",
            f"{err}\n\n詳細:\n{tb[-600:]}",
        )

    def _stop_player_server(self):
        if not self._player_running or self._player_server is None:
            return
        self._player_server.should_exit = True
        self._log("🎬 プレイヤー停止要求")
        self.root.after(500, self._refresh_player_btn)

    def _refresh_player_btn(self):
        if self._player_running:
            self.player_btn.config(text="⏹ プレイヤー停止")
        else:
            self.player_btn.config(text="🎬 プレイヤー起動")

    def _ensure_player_running(self) -> bool:
        """プレイヤーサーバが立っているか確認。立っていなければ起動を促し、port が
        listening になってから True を返す (port poll は _start_player_server 内で実装)。"""
        if self._player_running:
            return True
        if not messagebox.askyesno(
            "プレイヤー起動",
            "プレイヤーサーバが起動していません。今すぐ起動しますか？",
        ):
            return False
        return self._start_player_server()

    def _play_uuid(self, uuid: str):
        """ブラウザで /player/<uuid> を開く。

        判定ルール:
          - converted/<uuid>/ が存在しない → 再生不可
          - 存在する場合は (index 未確定でも) 再生を試みる
            (実際の妥当性は player ページが /api/videos/<uuid> で検証)
        """
        if uuid not in self._converted_dirs:
            messagebox.showwarning(
                "再生不可",
                f"{uuid[:12]}... はまだ HLS 変換されていません。\n"
                f"  hls-convert {self.folder}\n"
                "を実行してから再度お試しください。",
            )
            return
        if not self._ensure_player_running():
            return
        url = f"http://127.0.0.1:{self.player_port}/player/{uuid}"
        webbrowser.open(url)
        self._log(f"▶ 再生: {url}")

    def _play_selected(self):
        base = self._get_current_base()
        if not base:
            messagebox.showinfo("情報", "再生する行を選択してください。")
            return
        self._play_uuid(base)

    # ─── HTTP API ───

    def _start_api_server(self):
        """HTTP API サーバーを起動する（失敗してもGUIは継続）。"""
        port = self.api_port
        for attempt_port in (port, port + 1, port + 2):
            server, thread = start_api_server(self, attempt_port)
            if server is not None:
                self._api_server = server
                self._api_thread = thread
                self.api_port = attempt_port
                self._log(f"📡 API: http://127.0.0.1:{attempt_port}/status")
                return
        self._log(f"⚠ API サーバー起動失敗 (ポート {port}〜{port+2} 全て使用中)")

    def get_status_snapshot(self) -> dict:
        """API用: 集計情報を返す（スレッドセーフ: 参照コピーで取得）。"""
        status_map = dict(self.status_map)
        entries = list(self.entries)
        cat_to_key = {
            "✅ MP4済": "mp4", "🗑 MP4済(TS有)": "mp4_ts", "✅ TS済": "ts",
            "⏳ 未結合": "pending", "⚠ 不完全": "incomplete",
            "📥 未DL": "no_dl",
        }
        counts = {"mp4": 0, "mp4_ts": 0, "ts": 0,
                  "pending": 0, "incomplete": 0, "no_dl": 0, "scanning": 0}
        for cat in status_map.values():
            key = cat_to_key.get(cat)
            if key is not None:
                counts[key] += 1
            else:
                counts["scanning"] += 1
        return {
            "folder": self.folder,
            "index_file": self.index_file,
            "api_port": self.api_port,
            "total": len(entries),
            "counts": counts,
            "last_scan_at": self._last_scan_at,
        }

    def _format_entry(self, uuid: str, url: str, info: dict, status: str) -> dict:
        merged_mp4 = info.get("merged_mp4", {}) if info else {}
        merged_ts = info.get("merged_ts", {}) if info else {}
        return {
            "uuid": uuid,
            "url": url,
            "status": status,
            "part_count": info.get("part_count", 0) if info else 0,
            "total_size": info.get("total_size", 0) if info else 0,
            "complete": info.get("complete", False) if info else False,
            "expected_count": info.get("expected_count", 0) if info else 0,
            "missing": info.get("missing", []) if info else [],
            "has_mp4": merged_mp4.get("exists", False),
            "has_ts": merged_ts.get("exists", False),
            "split_mp4_count": len(info.get("split_mp4s", [])) if info else 0,
        }

    def get_entries_snapshot(self, filter_keyword: str | None = None) -> list[dict]:
        """API用: エントリ一覧。filter_keyword は status 文字列に部分一致。"""
        entries = list(self.entries)
        status_map = dict(self.status_map)
        url_map = dict(self.url_map)
        groups = dict(self.groups)

        result = []
        for entry in entries:
            uuid = entry["uuid"]
            cat = status_map.get(uuid, "🔍 スキャン中")
            if filter_keyword and filter_keyword not in cat:
                continue
            url = url_map.get(uuid, "")
            info = groups.get(uuid, {})
            result.append(self._format_entry(uuid, url, info, cat))
        return result

    def get_entry_detail(self, uuid: str) -> dict | None:
        """API用: 単一エントリの詳細情報。"""
        status_map = dict(self.status_map)
        url_map = dict(self.url_map)
        groups = dict(self.groups)

        if uuid not in status_map and uuid not in groups:
            return None

        url = url_map.get(uuid, "")
        cat = status_map.get(uuid, "🔍 スキャン中")
        info = groups.get(uuid, {})
        merged_mp4 = info.get("merged_mp4", {})
        merged_ts = info.get("merged_ts", {})

        return {
            "uuid": uuid,
            "url": url,
            "status": cat,
            "part_count": info.get("part_count", 0),
            "total_size": info.get("total_size", 0),
            "complete": info.get("complete", False),
            "expected_count": info.get("expected_count", 0),
            "missing": info.get("missing", []),
            "merged_mp4": {
                "exists": merged_mp4.get("exists", False),
                "size": merged_mp4.get("size", 0),
                "path": merged_mp4.get("path", ""),
            },
            "merged_ts": {
                "exists": merged_ts.get("exists", False),
                "size": merged_ts.get("size", 0),
                "path": merged_ts.get("path", ""),
            },
            "split_mp4s": [
                {"name": s["name"], "num": s["num"], "size": s["size"]}
                for s in info.get("split_mp4s", [])
            ],
            "parts": [
                {"name": p["name"], "num": p["num"], "size": p["size"]}
                for p in info.get("parts", [])
            ],
        }

    def trigger_rescan_from_api(self):
        """API用: メインスレッドで再スキャンをスケジュール。"""
        self.root.after(0, self._run_scan)

    def add_urls_from_api(self, urls: list) -> dict:
        """API用: URL群をindex.mdに追加 (重複は自動スキップ)。"""
        valid = []
        invalid = 0
        for u in urls:
            if isinstance(u, str) and PAT_INDEX_URL.search(u):
                valid.append(u.strip())
            else:
                invalid += 1
        if not valid:
            return {"ok": True, "added": 0, "skipped": 0, "invalid": invalid,
                    "message": "no valid urls"}
        added, skipped = add_to_index(self.folder, valid, self.index_file)
        # ログとスキャンはメインスレッドで実行
        self.root.after(0, lambda: self._log(
            f"📝 API経由で {added}件追加, {skipped}件重複, {invalid}件無効"))
        if added > 0:
            self.root.after(0, self._run_scan)
        return {"ok": True, "added": added, "skipped": skipped, "invalid": invalid}

    # ─── メインループ ───

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        if self._api_server is not None:
            try:
                self._api_server.shutdown()
                self._api_server.server_close()
            except Exception:
                pass
        if self._player_server is not None:
            try:
                self._player_server.should_exit = True
            except Exception:
                pass
        self.root.destroy()


def run_gui(
    folder: str,
    *,
    index_file: str | None = None,
    api_port: int = DEFAULT_API_PORT,
    player_port: int = 7860,
    start_player: bool = False,
    debug_enabled: bool = False,
) -> int:
    """GUI を起動するヘルパ。ts_merge.cli から呼ばれる。"""
    global DEBUG
    if debug_enabled:
        DEBUG = True
        debug("デバッグモード有効")

    folder = str(Path(folder).resolve())
    if not Path(folder).is_dir():
        print(f"エラー: ディレクトリが見つかりません: {folder}", file=sys.stderr)
        return 1

    debug(f"folder={folder}, index_file={index_file}, api_port={api_port}, "
          f"player_port={player_port}, start_player={start_player}")
    app = MainApp(
        folder, index_file=index_file, api_port=api_port,
        start_player=start_player, player_port=player_port,
    )
    app.run()
    return 0
