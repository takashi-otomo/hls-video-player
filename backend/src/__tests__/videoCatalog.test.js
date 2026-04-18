const fs = require('fs');
const os = require('os');
const path = require('path');
const { listVideos } = require('../utils/videoCatalog');

describe('listVideos', () => {
  let tmpRoot;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'hls-catalog-'));
    fs.mkdirSync(path.join(tmpRoot, 'hls'), { recursive: true });
    fs.mkdirSync(path.join(tmpRoot, 'sprites'), { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('returns empty array when no HLS outputs exist', () => {
    expect(listVideos(tmpRoot)).toEqual([]);
  });

  test('returns entries for each directory containing master.m3u8', () => {
    const videoDir = path.join(tmpRoot, 'hls', 'sample');
    fs.mkdirSync(videoDir, { recursive: true });
    fs.writeFileSync(path.join(videoDir, 'master.m3u8'), '#EXTM3U');

    const videos = listVideos(tmpRoot);
    expect(videos).toHaveLength(1);
    expect(videos[0].id).toBe('sample');
    expect(videos[0].masterUrl).toContain('sample/master.m3u8');
  });

  test('includes sprite metadata when sprite.jpg and thumbs.vtt exist', () => {
    const id = 'demo';
    const videoDir = path.join(tmpRoot, 'hls', id);
    fs.mkdirSync(videoDir, { recursive: true });
    fs.writeFileSync(path.join(videoDir, 'master.m3u8'), '#EXTM3U');
    fs.writeFileSync(path.join(tmpRoot, 'sprites', `${id}.jpg`), 'fake');
    fs.writeFileSync(path.join(tmpRoot, 'sprites', `${id}.vtt`), 'WEBVTT');
    fs.writeFileSync(path.join(tmpRoot, 'sprites', `${id}.json`), JSON.stringify({
      tileWidth: 160, tileHeight: 90, columns: 10, interval: 10,
    }));

    const videos = listVideos(tmpRoot);
    expect(videos[0].sprite).toEqual({
      url: expect.stringContaining(`${id}.jpg`),
      vttUrl: expect.stringContaining(`${id}.vtt`),
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      interval: 10,
    });
  });
});
