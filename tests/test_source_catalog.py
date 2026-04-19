"""sourceCatalog.test.js からの移植。"""

import json

from hls_video.source_catalog import list_sources, resolve_video_id


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
