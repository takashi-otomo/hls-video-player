"""ffmpegRunner.js からの移植 + 追加の結合テスト。"""

import json
import os
import subprocess

import pytest

from hls_video.ffmpeg_runner import (
    build_invocation,
    run_ffmpeg,
    probe_duration_seconds,
)


class TestBuildInvocation:
    def test_returns_bare_when_nice_unset(self, monkeypatch):
        monkeypatch.delenv("FFMPEG_NICE", raising=False)
        cmd, args = build_invocation("ffmpeg", ["-i", "in.mp4"])
        assert cmd == "ffmpeg"
        assert args == ["-i", "in.mp4"]

    def test_prepends_nice_on_unix(self, monkeypatch):
        monkeypatch.setenv("FFMPEG_NICE", "10")
        cmd, args = build_invocation("ffmpeg", ["-i", "in.mp4"])
        if os.name == "nt":
            assert cmd == "ffmpeg"
        else:
            assert cmd == "nice"
            assert args[:4] == ["-n", "10", "ffmpeg", "-i"]

    def test_ignores_invalid_nice(self, monkeypatch):
        monkeypatch.setenv("FFMPEG_NICE", "abc")
        cmd, _ = build_invocation("ffmpeg", [])
        assert cmd == "ffmpeg"


class TestRunFfmpeg:
    """/bin/echo などをダミー実行バイナリとして挙動確認。"""

    def test_captures_stderr_chunks(self, tmp_path):
        # ffmpeg の代わりに、python で stderr を出して正常終了するスクリプト
        script = tmp_path / "fake_ffmpeg.sh"
        script.write_text("#!/bin/sh\n>&2 echo 'line1'\n>&2 echo 'line2'\nexit 0\n")
        script.chmod(0o755)
        captured: list[str] = []
        run_ffmpeg([], ffmpeg_path=str(script), on_progress=lambda chunk: captured.append(chunk))
        assert "line1" in "".join(captured)
        assert "line2" in "".join(captured)

    def test_raises_on_nonzero_exit(self, tmp_path):
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/sh\n>&2 echo 'oops'\nexit 2\n")
        script.chmod(0o755)
        with pytest.raises(RuntimeError) as e:
            run_ffmpeg([], ffmpeg_path=str(script))
        assert "exit" in str(e.value).lower() or "2" in str(e.value)


@pytest.mark.skipif(
    subprocess.run(["which", "ffprobe"], capture_output=True).returncode != 0,
    reason="ffprobe not installed on this host",
)
class TestProbeDurationSeconds:
    def test_probes_real_file(self, tmp_path):
        # 5 秒の無音動画を FFmpeg で生成して ffprobe で計測
        out = tmp_path / "tiny.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=size=64x64:rate=1:duration=5",
             "-pix_fmt", "yuv420p", str(out)],
            check=True,
        )
        duration = probe_duration_seconds(str(out))
        assert 4.5 <= duration <= 5.5
