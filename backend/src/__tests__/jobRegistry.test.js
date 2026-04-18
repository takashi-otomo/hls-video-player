const { createJobRegistry } = require('../utils/jobRegistry');

describe('jobRegistry', () => {
  test('creates a pending job with unique id', () => {
    const reg = createJobRegistry();
    const a = reg.create({ videoId: 'a', sourceFile: 'a.mp4' });
    const b = reg.create({ videoId: 'b', sourceFile: 'b.mp4' });
    expect(a.id).not.toBe(b.id);
    expect(a.state).toBe('pending');
    expect(a.videoId).toBe('a');
  });

  test('retrieves jobs by id', () => {
    const reg = createJobRegistry();
    const job = reg.create({ videoId: 'x', sourceFile: 'x.mp4' });
    expect(reg.get(job.id)).toEqual(job);
  });

  test('updates state transitions to running/completed', () => {
    const reg = createJobRegistry();
    const job = reg.create({ videoId: 'x', sourceFile: 'x.mp4' });
    reg.update(job.id, { state: 'running' });
    expect(reg.get(job.id).state).toBe('running');
    reg.update(job.id, { state: 'completed' });
    expect(reg.get(job.id).state).toBe('completed');
  });

  test('marks failed with error message', () => {
    const reg = createJobRegistry();
    const job = reg.create({ videoId: 'x', sourceFile: 'x.mp4' });
    reg.update(job.id, { state: 'failed', error: 'boom' });
    expect(reg.get(job.id).state).toBe('failed');
    expect(reg.get(job.id).error).toBe('boom');
  });

  test('findActiveByVideoId returns pending or running job', () => {
    const reg = createJobRegistry();
    const j = reg.create({ videoId: 'x', sourceFile: 'x.mp4' });
    expect(reg.findActiveByVideoId('x')).toEqual(j);
    reg.update(j.id, { state: 'completed' });
    expect(reg.findActiveByVideoId('x')).toBeNull();
  });

  test('list returns most-recent-first', () => {
    const reg = createJobRegistry();
    const a = reg.create({ videoId: 'a', sourceFile: 'a.mp4' });
    const b = reg.create({ videoId: 'b', sourceFile: 'b.mp4' });
    const all = reg.list();
    expect(all[0].id).toBe(b.id);
    expect(all[1].id).toBe(a.id);
  });
});
