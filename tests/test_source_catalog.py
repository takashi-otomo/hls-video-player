"""sourceCatalog.test.js からの移植 + HLS-only と delete_source_file のテスト。"""

import json

from hls_video.source_catalog import (
    list_sources,
    resolve_video_id,
    delete_source_file,
)


def _bootstrap(tmp_path):
    (tmp_path / "source").mkdir(parents=True, exist_ok=True)
    (tmp_path / "hls").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sprites").mkdir(parents=True, exist_ok=True)


class TestResolveVideoId:
    def test_strips_extension(self):
        assert resolve_video_id("foo.mp4") == "foo"

    def test_sanitizes_invalid(self):
        assert resolve_video_id("hello world.MOV") == "hello_world"
        assert resolve_video_id("foo@bar?.mp4") == "foo_bar_"

    def test_preserves_hyphen_and_underscore(self):
        assert resolve_video_id("my-video_v2.mp4") == "my-video_v2"


class TestListSources:
    def test_empty_dir(self, tmp_path):
        _bootstrap(tmp_path)
        assert list_sources(str(tmp_path)) == []

    def test_ignores_non_video(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "README.md").write_text("hi")
        (tmp_path / "source" / ".DS_Store").write_text("")
        assert list_sources(str(tmp_path)) == []

    def test_lists_mp4_as_not_converted(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "a.mp4").write_bytes(b"AAA")
        result = list_sources(str(tmp_path))
        assert len(result) == 1
        assert result[0]["filename"] == "a.mp4"
        assert result[0]["video_id"] == "a"
        assert result[0]["size_bytes"] == 3
        assert result[0]["converted"] is False
        assert result[0]["sprite"] is None

    def test_marks_converted_when_master_exists(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "b.mp4").write_bytes(b"BB")
        (tmp_path / "hls" / "b").mkdir()
        (tmp_path / "hls" / "b" / "master.m3u8").write_text("#EXTM3U")
        result = list_sources(str(tmp_path))
        assert result[0]["converted"] is True

    def test_includes_sprite_for_converted(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "c.mp4").write_bytes(b"CC")
        (tmp_path / "hls" / "c").mkdir()
        (tmp_path / "hls" / "c" / "master.m3u8").write_text("#EXTM3U")
        (tmp_path / "sprites" / "c.jpg").write_bytes(b"x")
        (tmp_path / "sprites" / "c.json").write_text(json.dumps({
            "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
            "interval": 10, "tileCount": 3, "sheetCount": 1,
        }))
        result = list_sources(str(tmp_path))
        assert result[0]["sprite"]["sheets"] == ["/sprites/c.jpg"]
        assert result[0]["sprite"]["rows"] == 10

    def test_supports_multiple_extensions(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "a.mp4").write_bytes(b"")
        (tmp_path / "source" / "b.MOV").write_bytes(b"")
        (tmp_path / "source" / "c.mkv").write_bytes(b"")
        (tmp_path / "source" / "d.webm").write_bytes(b"")
        names = sorted(s["filename"] for s in list_sources(str(tmp_path)))
        assert names == ["a.mp4", "b.MOV", "c.mkv", "d.webm"]

    def test_sorted_alphabetically(self, tmp_path):
        _bootstrap(tmp_path)
        for n in ["c.mp4", "a.mp4", "b.mp4"]:
            (tmp_path / "source" / n).write_bytes(b"")
        names = [s["filename"] for s in list_sources(str(tmp_path))]
        assert names == ["a.mp4", "b.mp4", "c.mp4"]

    def test_source_deleted_flag_for_source_only(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "a.mp4").write_bytes(b"")
        res = list_sources(str(tmp_path))
        assert res[0]["source_deleted"] is False

    def test_includes_hls_only_as_source_deleted(self, tmp_path):
        """source/ に原本が無くても hls/ があれば列挙される (source_deleted=True)。"""
        _bootstrap(tmp_path)
        (tmp_path / "hls" / "orphan").mkdir()
        (tmp_path / "hls" / "orphan" / "master.m3u8").write_text("#EXTM3U")
        res = list_sources(str(tmp_path))
        assert len(res) == 1
        assert res[0]["video_id"] == "orphan"
        assert res[0]["source_deleted"] is True
        assert res[0]["converted"] is True

    def test_hls_only_includes_sprite_when_available(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "hls" / "demo").mkdir()
        (tmp_path / "hls" / "demo" / "master.m3u8").write_text("#EXTM3U")
        (tmp_path / "sprites" / "demo.jpg").write_bytes(b"x")
        (tmp_path / "sprites" / "demo.json").write_text(json.dumps({
            "tileWidth": 160, "tileHeight": 90, "columns": 10, "rows": 10,
            "interval": 10, "tileCount": 3, "sheetCount": 1,
        }))
        res = list_sources(str(tmp_path))
        assert res[0]["sprite"]["sheets"] == ["/sprites/demo.jpg"]

    def test_does_not_duplicate_when_both_source_and_hls_exist(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "v.mp4").write_bytes(b"")
        (tmp_path / "hls" / "v").mkdir()
        (tmp_path / "hls" / "v" / "master.m3u8").write_text("#EXTM3U")
        res = list_sources(str(tmp_path))
        assert len(res) == 1
        assert res[0]["source_deleted"] is False


class TestDeleteSourceFile:
    def test_removes_regular_file(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "a.mp4").write_bytes(b"data")
        res = delete_source_file(str(tmp_path), "a.mp4")
        assert res["ok"] is True
        assert not (tmp_path / "source" / "a.mp4").exists()

    def test_returns_not_found(self, tmp_path):
        _bootstrap(tmp_path)
        res = delete_source_file(str(tmp_path), "nope.mp4")
        assert res["ok"] is False
        assert "見つかりません" in res["message"]

    def test_rejects_path_traversal(self, tmp_path):
        _bootstrap(tmp_path)
        # secret ファイルを source/ の外に配置
        (tmp_path / "secret.txt").write_text("SECRET")
        res = delete_source_file(str(tmp_path), "../secret.txt")
        assert res["ok"] is False
        # secret は残っているはず
        assert (tmp_path / "secret.txt").exists()

    def test_keeps_hls_and_sprites_intact(self, tmp_path):
        _bootstrap(tmp_path)
        (tmp_path / "source" / "v.mp4").write_bytes(b"x")
        (tmp_path / "hls" / "v").mkdir()
        (tmp_path / "hls" / "v" / "master.m3u8").write_text("#EXTM3U")
        (tmp_path / "sprites" / "v.jpg").write_bytes(b"")
        delete_source_file(str(tmp_path), "v.mp4")
        assert (tmp_path / "hls" / "v" / "master.m3u8").exists()
        assert (tmp_path / "sprites" / "v.jpg").exists()
