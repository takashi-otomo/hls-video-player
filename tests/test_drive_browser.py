"""Drive ブラウズ & ファイル取り込みのテスト。"""

import os
from pathlib import Path

import pytest

from hls_video.drive_browser import (
    BrowseEntry,
    list_videos_under,
    import_file,
    purge_stale_staging,
    stage_to_local,
)


class TestListVideosUnder:
    def test_returns_empty_for_missing_dir(self, tmp_path):
        assert list_videos_under(str(tmp_path / "nope")) == []

    def test_lists_only_video_extensions(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"")
        (tmp_path / "b.txt").write_text("")
        (tmp_path / "c.mov").write_bytes(b"")
        result = list_videos_under(str(tmp_path))
        names = sorted(e.rel for e in result)
        assert names == ["a.mp4", "c.mov"]

    def test_walks_nested_dirs(self, tmp_path):
        (tmp_path / "dir1").mkdir()
        (tmp_path / "dir1" / "a.mp4").write_bytes(b"")
        (tmp_path / "dir1" / "nested").mkdir()
        (tmp_path / "dir1" / "nested" / "b.webm").write_bytes(b"")
        result = list_videos_under(str(tmp_path))
        rels = sorted(e.rel for e in result)
        assert "dir1/a.mp4" in rels
        assert "dir1/nested/b.webm" in rels

    def test_respects_max_depth(self, tmp_path):
        p = tmp_path
        for i in range(5):
            p = p / f"d{i}"
            p.mkdir()
        (p / "deep.mp4").write_bytes(b"")
        shallow = list_videos_under(str(tmp_path), max_depth=2)
        assert shallow == []
        deep = list_videos_under(str(tmp_path), max_depth=10)
        assert any(e.rel.endswith("deep.mp4") for e in deep)

    def test_skips_hidden_and_known_dirs(self, tmp_path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "x.mp4").write_bytes(b"")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "y.mp4").write_bytes(b"")
        (tmp_path / "regular.mp4").write_bytes(b"")
        result = list_videos_under(str(tmp_path))
        rels = [e.rel for e in result]
        assert rels == ["regular.mp4"]

    def test_does_not_follow_symlinks(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "hidden.mp4").write_bytes(b"")
        link = tmp_path / "link_to_real"
        os.symlink(real, link)
        result = list_videos_under(str(tmp_path))
        rels = [e.rel for e in result]
        assert rels == ["real/hidden.mp4"]

    def test_mtime_is_populated(self, tmp_path):
        (tmp_path / "a.mp4").write_bytes(b"")
        result = list_videos_under(str(tmp_path))
        assert result[0].mtime > 0

    def test_already_imported_flag(self, tmp_path):
        drive = tmp_path / "drive"
        drive.mkdir()
        (drive / "already.mp4").write_bytes(b"")
        (drive / "fresh.mp4").write_bytes(b"")

        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        (media / "source" / "already.mp4").write_bytes(b"existing")

        result = list_videos_under(str(drive), media_root=str(media))
        by_name = {e.rel: e for e in result}
        assert by_name["already.mp4"].already_imported is True
        assert by_name["fresh.mp4"].already_imported is False

    def test_already_imported_false_when_media_root_missing(self, tmp_path):
        drive = tmp_path / "drive"
        drive.mkdir()
        (drive / "v.mp4").write_bytes(b"")
        # media_root 未指定
        result = list_videos_under(str(drive))
        assert result[0].already_imported is False

    def test_already_imported_when_converted_but_source_deleted(self, tmp_path):
        """media/source/ に同名ファイルが無くても、対応する変換済 HLS があれば重複扱い。"""
        drive = tmp_path / "drive"
        drive.mkdir()
        (drive / "movie.mp4").write_bytes(b"")

        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        (media / "hls" / "movie").mkdir(parents=True)
        (media / "hls" / "movie" / "master.m3u8").write_text("#EXTM3U")

        result = list_videos_under(str(drive), media_root=str(media))
        assert result[0].already_imported is True

    def test_already_imported_considers_sanitized_video_id(self, tmp_path):
        """video_id は resolve_video_id でサニタイズされた値で比較する。"""
        drive = tmp_path / "drive"
        drive.mkdir()
        (drive / "my video.mp4").write_bytes(b"")  # 空白あり → video_id=my_video

        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        (media / "hls" / "my_video").mkdir(parents=True)
        (media / "hls" / "my_video" / "master.m3u8").write_text("#EXTM3U")

        result = list_videos_under(str(drive), media_root=str(media))
        assert result[0].already_imported is True


class TestImportFile:
    def test_copies_to_media_source(self, tmp_path):
        media = tmp_path / "media"
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"DATA")

        result = import_file(str(src), str(media))
        assert result["ok"] is True
        assert "コピー" in result["message"]
        dst = media / "source" / "movie.mp4"
        assert dst.is_file()
        assert not dst.is_symlink()
        assert dst.read_bytes() == b"DATA"
        # 元ファイルは変更されない
        assert src.read_bytes() == b"DATA"

    def test_rejects_missing_file(self, tmp_path):
        result = import_file(str(tmp_path / "nope.mp4"), str(tmp_path))
        assert result["ok"] is False
        assert "見つかりません" in result["message"]

    def test_rejects_non_video_extension(self, tmp_path):
        src = tmp_path / "doc.txt"
        src.write_text("")
        result = import_file(str(src), str(tmp_path))
        assert result["ok"] is False
        assert "拡張子" in result["message"]

    def test_refuses_overwrite_by_default(self, tmp_path):
        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        existing = media / "source" / "movie.mp4"
        existing.write_bytes(b"existing")
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"new")

        result = import_file(str(src), str(media))
        assert result["ok"] is False
        assert "既に" in result["message"]
        # 既存ファイルは変更されない
        assert (media / "source" / "movie.mp4").read_bytes() == b"existing"

    def test_overwrites_when_allowed(self, tmp_path):
        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        old = media / "source" / "movie.mp4"
        old.write_bytes(b"old")
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"new")

        result = import_file(str(src), str(media), overwrite=True)
        assert result["ok"] is True
        dst = media / "source" / "movie.mp4"
        assert dst.is_file()
        assert dst.read_bytes() == b"new"


class TestStageToLocal:
    def test_copies_to_staging(self, tmp_path):
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"DATA")
        staging = tmp_path / "stage"

        res = stage_to_local(str(src), str(staging))
        assert res["ok"] is True
        assert res["path"] == str(staging / "movie.mp4")
        assert (staging / "movie.mp4").read_bytes() == b"DATA"
        assert src.read_bytes() == b"DATA"  # 元は残る

    def test_skips_copy_when_already_staged_with_same_size(self, tmp_path):
        src = tmp_path / "drive" / "v.mp4"
        src.parent.mkdir()
        src.write_bytes(b"ABCDEF")
        staging = tmp_path / "stage"
        # 事前に同サイズの既存
        staging.mkdir()
        (staging / "v.mp4").write_bytes(b"QQQQQQ")  # 6 bytes like src

        res = stage_to_local(str(src), str(staging))
        assert res["ok"] is True
        # skip されたので中身は古い値のまま
        assert (staging / "v.mp4").read_bytes() == b"QQQQQQ"

    def test_rejects_missing(self, tmp_path):
        res = stage_to_local(str(tmp_path / "nope.mp4"), str(tmp_path / "stage"))
        assert res["ok"] is False
        assert res["path"] is None

    def test_rejects_non_video_extension(self, tmp_path):
        src = tmp_path / "doc.txt"
        src.write_text("")
        res = stage_to_local(str(src), str(tmp_path / "stage"))
        assert res["ok"] is False


class TestPurgeStaleStaging:
    def test_returns_zero_when_dir_missing(self, tmp_path):
        assert purge_stale_staging(str(tmp_path / "nope")) == 0

    def test_removes_old_video_files(self, tmp_path):
        import time as _time
        staging = tmp_path / "stage"
        staging.mkdir()
        old = staging / "old.mp4"
        old.write_bytes(b"X")
        # mtime を 2 時間前に
        old_time = _time.time() - 7200
        os.utime(old, (old_time, old_time))

        removed = purge_stale_staging(str(staging), older_than_seconds=3600)
        assert removed == 1
        assert not old.exists()

    def test_keeps_fresh_files(self, tmp_path):
        staging = tmp_path / "stage"
        staging.mkdir()
        fresh = staging / "fresh.mp4"
        fresh.write_bytes(b"X")

        removed = purge_stale_staging(str(staging), older_than_seconds=3600)
        assert removed == 0
        assert fresh.exists()

    def test_ignores_non_video_files(self, tmp_path):
        import time as _time
        staging = tmp_path / "stage"
        staging.mkdir()
        log = staging / "notes.txt"
        log.write_text("keep me")
        old_time = _time.time() - 7200
        os.utime(log, (old_time, old_time))

        removed = purge_stale_staging(str(staging), older_than_seconds=3600)
        assert removed == 0
        assert log.exists()

    def test_stage_to_local_triggers_purge(self, tmp_path):
        """stage_to_local 呼び出し時に古い孤児ファイルが自動掃除される。"""
        import time as _time
        staging = tmp_path / "stage"
        staging.mkdir()
        orphan = staging / "orphan.mp4"
        orphan.write_bytes(b"OLD")
        old_time = _time.time() - 7200
        os.utime(orphan, (old_time, old_time))

        src = tmp_path / "drive" / "new.mp4"
        src.parent.mkdir()
        src.write_bytes(b"NEW")

        res = stage_to_local(str(src), str(staging))
        assert res["ok"] is True
        assert not orphan.exists(), "古いステージングが掃除されるはず"
        assert (staging / "new.mp4").exists()
