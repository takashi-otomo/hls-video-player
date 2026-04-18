const { computeSpriteCoordinates, generateVttContent } = require('../utils/vttBuilder');

describe('computeSpriteCoordinates', () => {
  const tileWidth = 160;
  const tileHeight = 90;
  const columns = 10;

  test('returns (0,0) for index 0', () => {
    expect(computeSpriteCoordinates(0, columns, tileWidth, tileHeight)).toEqual({ x: 0, y: 0 });
  });

  test('advances along X for indices within first row', () => {
    expect(computeSpriteCoordinates(3, columns, tileWidth, tileHeight)).toEqual({ x: 480, y: 0 });
  });

  test('wraps to next row when column count reached', () => {
    expect(computeSpriteCoordinates(10, columns, tileWidth, tileHeight)).toEqual({ x: 0, y: 90 });
  });

  test('computes correct (x,y) for index 12 with 10 columns', () => {
    // From the research document: index 12 with C=10, W=160, H=90 → (320, 90)
    expect(computeSpriteCoordinates(12, columns, tileWidth, tileHeight)).toEqual({ x: 320, y: 90 });
  });
});

describe('generateVttContent', () => {
  test('emits valid WEBVTT header', () => {
    const vtt = generateVttContent({
      spriteUrl: 'sprite.jpg',
      tileCount: 1,
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      intervalSeconds: 10,
    });
    expect(vtt.startsWith('WEBVTT')).toBe(true);
  });

  test('produces one cue per tile with correct time ranges', () => {
    const vtt = generateVttContent({
      spriteUrl: 'sprite.jpg',
      tileCount: 3,
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      intervalSeconds: 10,
    });
    expect(vtt).toContain('00:00:00.000 --> 00:00:10.000');
    expect(vtt).toContain('00:00:10.000 --> 00:00:20.000');
    expect(vtt).toContain('00:00:20.000 --> 00:00:30.000');
  });

  test('appends Media Fragments URI with xywh coordinates', () => {
    const vtt = generateVttContent({
      spriteUrl: 'sprite.jpg',
      tileCount: 2,
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      intervalSeconds: 10,
    });
    expect(vtt).toContain('sprite.jpg#xywh=0,0,160,90');
    expect(vtt).toContain('sprite.jpg#xywh=160,0,160,90');
  });

  test('formats hour boundary correctly', () => {
    const vtt = generateVttContent({
      spriteUrl: 'sprite.jpg',
      tileCount: 361,
      tileWidth: 160,
      tileHeight: 90,
      columns: 10,
      intervalSeconds: 10,
    });
    expect(vtt).toContain('01:00:00.000 --> 01:00:10.000');
  });
});
