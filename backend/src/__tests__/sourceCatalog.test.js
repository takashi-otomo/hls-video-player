const fs = require('fs');
const os = require('os');
const path = require('path');
const { listSources, resolveVideoId } = require('../utils/sourceCatalog');

describe('resolveVideoId', () => {
  test('strips extension', () => {
    expect(resolveVideoId('foo.mp4')).toBe('foo');
  });

  test('sanitizes invalid characters', () => {
    expect(resolveVideoId('hello world.MOV')).toBe('hello_world');
    expect(resolveVideoId('fo@o?.mp4')).toBe('fo_o_');
  });

  test('preserves hyphens and underscores', () => {
    expect(resolveVideoId('my-video_v2.mp4')).toBe('my-video_v2');
  });
});

describe('listSources', () => {
  let tmpRoot;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'hls-src-'));
    fs.mkdirSync(path.join(tmpRoot, 'source'), { recursive: true });
    fs.mkdirSync(path.join(tmpRoot, 'hls'), { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('returns empty array when source dir has no videos', () => {
    expect(listSources(tmpRoot)).toEqual([]);
  });

  test('ignores README and non-video files', () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'README.md'), 'hi');
    fs.writeFileSync(path.join(tmpRoot, 'source', '.DS_Store'), '');
    expect(listSources(tmpRoot)).toEqual([]);
  });

  test('lists .mp4 files with size and converted=false', () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'a.mp4'), 'AAA');
    const result = listSources(tmpRoot);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      filename: 'a.mp4',
      videoId: 'a',
      sizeBytes: 3,
      converted: false,
      sprite: null,
    });
    expect(typeof result[0].modifiedAt).toBe('string');
  });

  test('marks converted=true when master.m3u8 exists in hls/<id>/', () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'b.mp4'), 'BB');
    fs.mkdirSync(path.join(tmpRoot, 'hls', 'b'), { recursive: true });
    fs.writeFileSync(path.join(tmpRoot, 'hls', 'b', 'master.m3u8'), '#EXTM3U');
    const result = listSources(tmpRoot);
    expect(result[0].converted).toBe(true);
  });

  test('includes sprite info for converted sources (for card thumbnails)', () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'c.mp4'), 'CC');
    fs.mkdirSync(path.join(tmpRoot, 'hls', 'c'), { recursive: true });
    fs.writeFileSync(path.join(tmpRoot, 'hls', 'c', 'master.m3u8'), '#EXTM3U');
    fs.mkdirSync(path.join(tmpRoot, 'sprites'), { recursive: true });
    fs.writeFileSync(path.join(tmpRoot, 'sprites', 'c.jpg'), 'fake');
    fs.writeFileSync(path.join(tmpRoot, 'sprites', 'c.vtt'), 'WEBVTT');
    fs.writeFileSync(path.join(tmpRoot, 'sprites', 'c.json'), JSON.stringify({
      tileWidth: 160, tileHeight: 90, columns: 10, rows: 10, interval: 10, tileCount: 3, sheetCount: 1,
    }));
    const result = listSources(tmpRoot);
    expect(result[0].sprite).toMatchObject({
      sheets: ['/sprites/c.jpg'],
      sheetCount: 1,
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      rows: 10,
    });
  });

  test('supports common video extensions (.mov, .mkv, .webm)', () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'a.mp4'), '');
    fs.writeFileSync(path.join(tmpRoot, 'source', 'b.MOV'), '');
    fs.writeFileSync(path.join(tmpRoot, 'source', 'c.mkv'), '');
    fs.writeFileSync(path.join(tmpRoot, 'source', 'd.webm'), '');
    const result = listSources(tmpRoot).map((s) => s.filename).sort();
    expect(result).toEqual(['a.mp4', 'b.MOV', 'c.mkv', 'd.webm']);
  });
});
