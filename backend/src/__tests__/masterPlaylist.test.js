const { buildMasterPlaylist } = require('../utils/masterPlaylist');

describe('buildMasterPlaylist', () => {
  test('emits EXTM3U header', () => {
    const master = buildMasterPlaylist([
      { bandwidth: 400000, resolution: '426x240', playlist: '240p.m3u8' },
    ]);
    expect(master.split('\n')[0]).toBe('#EXTM3U');
  });

  test('emits one STREAM-INF block per variant', () => {
    const master = buildMasterPlaylist([
      { bandwidth: 3000000, resolution: '1280x720', playlist: '720p.m3u8' },
      { bandwidth: 1500000, resolution: '854x480', playlist: '480p.m3u8' },
    ]);
    const streamInfCount = (master.match(/#EXT-X-STREAM-INF/g) || []).length;
    expect(streamInfCount).toBe(2);
    expect(master).toContain('BANDWIDTH=3000000');
    expect(master).toContain('RESOLUTION=1280x720');
    expect(master).toContain('720p.m3u8');
  });

  test('throws when variants list is empty', () => {
    expect(() => buildMasterPlaylist([])).toThrow();
  });
});
