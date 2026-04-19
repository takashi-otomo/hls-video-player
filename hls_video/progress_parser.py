"""FFmpeg stderr の `time=HH:MM:SS.mmm` を抽出し、duration 比で進捗率 (0-1) を計算する。

Node 側 utils/progressParser.js と 1:1 の挙動を保つ。
multi-output 時は同一チャンクに複数 time= が現れるため、最後の出現を採用する。
"""

from __future__ import annotations

import re
from typing import Callable, Optional

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def parse_latest_timestamp(text: str) -> Optional[float]:
    """text 内に現れる time= のうち最後のひとつを秒数に変換して返す。"""
    matches = _TIME_RE.findall(text)
    if not matches:
        return None
    h_str, m_str, s_str = matches[-1]
    try:
        return int(h_str) * 3600 + int(m_str) * 60 + float(s_str)
    except (TypeError, ValueError):
        return None


def compute_ratio(current_seconds: float, duration_seconds: Optional[float]) -> Optional[float]:
    """進捗率 (0..1) を返す。duration 不正なら None。"""
    if not duration_seconds or duration_seconds <= 0:
        return None
    if current_seconds is None or current_seconds < 0:
        return 0.0
    return max(0.0, min(1.0, current_seconds / duration_seconds))


def create_progress_parser(
    *,
    duration_seconds: Optional[float],
    on_ratio: Callable[[float, dict], None],
) -> Callable[[str], None]:
    """stderr チャンクを受け取り、進捗率が上がったときだけ on_ratio を呼ぶコールバックを返す。

    - 逆戻り (再試行時の time= 減少) は無視する（monotonic）。
    - duration 未指定の場合は何もしない。
    - on_ratio のコールバック内例外は swallow する（UI 側エラーで計測が止まらないよう）。
    """

    state = {"last_time": -1.0}

    def _feed(chunk: str) -> None:
        t = parse_latest_timestamp(chunk)
        if t is None:
            return
        if t <= state["last_time"]:
            return
        state["last_time"] = t
        ratio = compute_ratio(t, duration_seconds)
        if ratio is None:
            return
        try:
            on_ratio(ratio, {"current_time": t})
        except Exception:
            pass

    return _feed
