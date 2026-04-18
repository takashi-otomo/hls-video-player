const { buildVariantArgs, DEFAULT_VARIANTS } = require('../utils/hlsConverter');
const { buildInvocation } = require('../utils/ffmpegRunner');

describe('buildVariantArgs – CPU/threads throttling', () => {
  const v = DEFAULT_VARIANTS[0];

  test('includes -preset and -threads when provided', () => {
    const args = buildVariantArgs(v, '/tmp', 4, 48, { preset: 'veryfast', threads: 2 });
    const presetIdx = args.indexOf('-preset');
    const threadsIdx = args.indexOf('-threads');
    expect(presetIdx).toBeGreaterThan(-1);
    expect(args[presetIdx + 1]).toBe('veryfast');
    expect(threadsIdx).toBeGreaterThan(-1);
    expect(args[threadsIdx + 1]).toBe('2');
  });

  test('threads can be tightened to 1', () => {
    const args = buildVariantArgs(v, '/tmp', 4, 48, { preset: 'ultrafast', threads: 1 });
    const threadsIdx = args.indexOf('-threads');
    expect(args[threadsIdx + 1]).toBe('1');
  });
});

describe('buildInvocation – nice wrapping', () => {
  const originalEnv = process.env.FFMPEG_NICE;
  afterEach(() => {
    if (originalEnv === undefined) delete process.env.FFMPEG_NICE;
    else process.env.FFMPEG_NICE = originalEnv;
  });

  test('returns bare ffmpeg when FFMPEG_NICE is unset', () => {
    delete process.env.FFMPEG_NICE;
    const { cmd, cmdArgs } = buildInvocation('ffmpeg', ['-i', 'in.mp4']);
    expect(cmd).toBe('ffmpeg');
    expect(cmdArgs).toEqual(['-i', 'in.mp4']);
  });

  test('prepends nice when FFMPEG_NICE is set (on non-Windows)', () => {
    process.env.FFMPEG_NICE = '10';
    const { cmd, cmdArgs } = buildInvocation('ffmpeg', ['-i', 'in.mp4']);
    if (process.platform === 'win32') {
      // On Windows the wrapper is not applied — asserting the no-op fallback
      expect(cmd).toBe('ffmpeg');
    } else {
      expect(cmd).toBe('nice');
      expect(cmdArgs.slice(0, 4)).toEqual(['-n', '10', 'ffmpeg', '-i']);
    }
  });

  test('ignores malformed FFMPEG_NICE', () => {
    process.env.FFMPEG_NICE = 'abc';
    const { cmd } = buildInvocation('ffmpeg', []);
    expect(cmd).toBe('ffmpeg');
  });
});
