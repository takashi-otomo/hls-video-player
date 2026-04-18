const { parseLatestTimestamp, computeRatio, createProgressParser } = require('../utils/progressParser');

describe('parseLatestTimestamp', () => {
  test('extracts seconds from a typical FFmpeg stderr line', () => {
    const line = 'frame= 240 fps=120 q=26.0 size=  768kB time=00:00:10.00 bitrate=... speed=5.0x';
    expect(parseLatestTimestamp(line)).toBeCloseTo(10, 3);
  });

  test('returns the last match when multiple time= occur (multi-output)', () => {
    const line = 'out#0 time=00:00:05.00 out#1 time=00:00:07.50 out#2 time=00:00:09.25';
    expect(parseLatestTimestamp(line)).toBeCloseTo(9.25, 2);
  });

  test('returns null when no time= token is present', () => {
    expect(parseLatestTimestamp('no progress here')).toBeNull();
  });

  test('handles HH:MM:SS.mmm across minute/hour boundaries', () => {
    expect(parseLatestTimestamp('time=01:02:03.500')).toBeCloseTo(3723.5, 3);
  });
});

describe('computeRatio', () => {
  test('returns bounded ratio', () => {
    expect(computeRatio(30, 60)).toBeCloseTo(0.5);
    expect(computeRatio(120, 60)).toBe(1); // clamped
    expect(computeRatio(-1, 60)).toBe(0);   // clamped
  });

  test('returns null when duration is missing/zero', () => {
    expect(computeRatio(10, 0)).toBeNull();
    expect(computeRatio(10, null)).toBeNull();
  });
});

describe('createProgressParser', () => {
  test('emits monotonically increasing ratios', () => {
    const events = [];
    const parser = createProgressParser({
      durationSeconds: 10,
      onRatio: (r) => events.push(r),
    });
    parser('time=00:00:02.00');
    parser('time=00:00:05.00');
    parser('time=00:00:04.50'); // backtrack should be ignored
    parser('time=00:00:10.00');
    expect(events).toEqual([0.2, 0.5, 1]);
  });

  test('no-ops when duration is missing', () => {
    const events = [];
    const parser = createProgressParser({
      durationSeconds: null,
      onRatio: (r) => events.push(r),
    });
    parser('time=00:00:02.00');
    expect(events).toEqual([]);
  });
});
