"""progressParser.test.js からの移植。既存 Node 実装と 1:1 の挙動を要求。"""

import pytest

from hls_video.progress_parser import (
    parse_latest_timestamp,
    compute_ratio,
    create_progress_parser,
)


class TestParseLatestTimestamp:
    def test_extracts_seconds_from_typical_line(self):
        line = "frame= 240 fps=120 q=26.0 size=  768kB time=00:00:10.00 bitrate=... speed=5.0x"
        assert parse_latest_timestamp(line) == pytest.approx(10.0, abs=1e-3)

    def test_returns_last_match_when_multiple(self):
        line = "out#0 time=00:00:05.00 out#1 time=00:00:07.50 out#2 time=00:00:09.25"
        assert parse_latest_timestamp(line) == pytest.approx(9.25, abs=1e-2)

    def test_returns_none_when_no_match(self):
        assert parse_latest_timestamp("no progress here") is None

    def test_handles_hours_and_minutes(self):
        assert parse_latest_timestamp("time=01:02:03.500") == pytest.approx(3723.5, abs=1e-3)


class TestComputeRatio:
    def test_returns_bounded_ratio(self):
        assert compute_ratio(30, 60) == pytest.approx(0.5)
        assert compute_ratio(120, 60) == 1.0  # clamped
        assert compute_ratio(-1, 60) == 0.0  # clamped

    def test_returns_none_when_duration_missing(self):
        assert compute_ratio(10, 0) is None
        assert compute_ratio(10, None) is None


class TestCreateProgressParser:
    def test_emits_monotonically_increasing_ratios(self):
        events: list[float] = []
        parser = create_progress_parser(duration_seconds=10, on_ratio=lambda r, _meta: events.append(r))
        parser("time=00:00:02.00")
        parser("time=00:00:05.00")
        parser("time=00:00:04.50")  # backtrack → ignored
        parser("time=00:00:10.00")
        assert events == pytest.approx([0.2, 0.5, 1.0])

    def test_noop_when_duration_missing(self):
        events: list[float] = []
        parser = create_progress_parser(duration_seconds=None, on_ratio=lambda r, _meta: events.append(r))
        parser("time=00:00:02.00")
        assert events == []

    def test_meta_contains_current_time(self):
        metas: list[dict] = []
        parser = create_progress_parser(
            duration_seconds=10, on_ratio=lambda _r, meta: metas.append(meta)
        )
        parser("time=00:00:03.00")
        assert metas[0]["current_time"] == pytest.approx(3.0)
