"""Drive ブラウズ & シンボリックリンク取り込みのテスト。"""

import os
from pathlib import Path

import pytest

from hls_video.drive_browser import (
    BrowseEntry,
    list_videos_under,
    import_as_symlink,
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
        # 浅い deep 制限ではヒットしない
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
        # ベース直下の link_to_real は symlink で無視、real/hidden.mp4 は正規で拾われる
        result = list_videos_under(str(tmp_path))
        rels = [e.rel for e in result]
        assert rels == ["real/hidden.mp4"]


class TestImportAsSymlink:
    def test_creates_symlink_in_media_source(self, tmp_path):
        media = tmp_path / "media"
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"DATA")

        result = import_as_symlink(str(src), str(media))
        assert result["ok"] is True
        link = media / "source" / "movie.mp4"
        assert link.is_symlink()
        assert link.read_bytes() == b"DATA"  # シンボリック経由で実体を読めること
        assert os.readlink(link) == str(src.resolve())

    def test_rejects_missing_file(self, tmp_path):
        result = import_as_symlink(str(tmp_path / "nope.mp4"), str(tmp_path))
        assert result["ok"] is False
        assert "見つかりません" in result["message"]

    def test_rejects_non_video_extension(self, tmp_path):
        src = tmp_path / "doc.txt"
        src.write_text("")
        result = import_as_symlink(str(src), str(tmp_path))
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

        result = import_as_symlink(str(src), str(media))
        assert result["ok"] is False
        assert "既に" in result["message"]

    def test_overwrites_when_allowed(self, tmp_path):
        media = tmp_path / "media"
        (media / "source").mkdir(parents=True)
        old = media / "source" / "movie.mp4"
        old.write_bytes(b"old")
        src = tmp_path / "drive" / "movie.mp4"
        src.parent.mkdir()
        src.write_bytes(b"new")

        result = import_as_symlink(str(src), str(media), overwrite=True)
        assert result["ok"] is True
        assert (media / "source" / "movie.mp4").is_symlink()
