const fs = require('fs');
const os = require('os');
const path = require('path');
const request = require('supertest');
const { createApp } = require('../app');

describe('Express app', () => {
  let tmpRoot;
  let app;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'hls-app-'));
    fs.mkdirSync(path.join(tmpRoot, 'hls', 'sample'), { recursive: true });
    fs.mkdirSync(path.join(tmpRoot, 'sprites'), { recursive: true });
    fs.writeFileSync(path.join(tmpRoot, 'hls', 'sample', 'master.m3u8'), '#EXTM3U\n');
    app = createApp({ mediaRoot: tmpRoot });
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('GET /api/health returns ok', async () => {
    const res = await request(app).get('/api/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
  });

  test('GET /api/videos lists catalog entries', async () => {
    const res = await request(app).get('/api/videos');
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body)).toBe(true);
    expect(res.body[0].id).toBe('sample');
  });

  test('GET /hls/:id/master.m3u8 serves the playlist with correct MIME', async () => {
    const res = await request(app).get('/hls/sample/master.m3u8');
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toMatch(/application\/(vnd\.apple\.mpegurl|x-mpegURL)/i);
    expect(res.text).toContain('#EXTM3U');
  });

  test('GET /hls/:id/missing.m3u8 returns 404', async () => {
    const res = await request(app).get('/hls/sample/missing.m3u8');
    expect(res.status).toBe(404);
  });
});

describe('Source + conversion endpoints', () => {
  const { createApp } = require('../app');
  const { createJobRegistry } = require('../utils/jobRegistry');

  let tmpRoot;
  let app;
  let registry;
  let runnerCalls;
  let fakeRunner;

  beforeEach(() => {
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'hls-src-app-'));
    fs.mkdirSync(path.join(tmpRoot, 'source'), { recursive: true });
    fs.mkdirSync(path.join(tmpRoot, 'hls'), { recursive: true });
    fs.mkdirSync(path.join(tmpRoot, 'sprites'), { recursive: true });

    fs.writeFileSync(path.join(tmpRoot, 'source', 'movie.mp4'), 'X');

    registry = createJobRegistry();
    runnerCalls = [];
    fakeRunner = jest.fn((args) => {
      runnerCalls.push(args);
    });
    app = createApp({ mediaRoot: tmpRoot, registry, runner: fakeRunner });
  });

  afterEach(() => {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  });

  test('GET /api/sources lists files with converted=false', async () => {
    const res = await request(app).get('/api/sources');
    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(1);
    expect(res.body[0]).toMatchObject({
      filename: 'movie.mp4', videoId: 'movie', converted: false, activeJobId: null,
    });
  });

  test('POST /api/sources/:filename/convert creates a job and invokes runner', async () => {
    const res = await request(app).post('/api/sources/movie.mp4/convert').send({});
    expect(res.status).toBe(202);
    expect(res.body).toMatchObject({ videoId: 'movie' });
    expect(typeof res.body.jobId).toBe('string');

    // setImmediate fires after the handler returns
    await new Promise((r) => setImmediate(r));
    expect(fakeRunner).toHaveBeenCalledTimes(1);
    expect(fakeRunner.mock.calls[0][0]).toMatchObject({
      jobId: res.body.jobId, sourceFile: 'movie.mp4', videoId: 'movie',
    });
  });

  test('POST conversion for missing file returns 404', async () => {
    const res = await request(app).post('/api/sources/nope.mp4/convert').send({});
    expect(res.status).toBe(404);
  });

  test('POST conversion for unsupported extension returns 400', async () => {
    fs.writeFileSync(path.join(tmpRoot, 'source', 'doc.txt'), '');
    const res = await request(app).post('/api/sources/doc.txt/convert').send({});
    expect(res.status).toBe(400);
  });

  test('POST returns 409 when already converted', async () => {
    fs.mkdirSync(path.join(tmpRoot, 'hls', 'movie'), { recursive: true });
    fs.writeFileSync(path.join(tmpRoot, 'hls', 'movie', 'master.m3u8'), '#EXTM3U');
    const res = await request(app).post('/api/sources/movie.mp4/convert').send({});
    expect(res.status).toBe(409);
    expect(res.body.error).toBe('already_converted');
  });

  test('POST returns 409 when a job is already active for this videoId', async () => {
    registry.create({ videoId: 'movie', sourceFile: 'movie.mp4' }); // default state: pending
    const res = await request(app).post('/api/sources/movie.mp4/convert').send({});
    expect(res.status).toBe(409);
    expect(res.body.error).toBe('already_running');
  });

  test('POST rejects path traversal attempts', async () => {
    const res = await request(app).post('/api/sources/..%2Fsecret.mp4/convert').send({});
    expect([400, 404]).toContain(res.status);
  });

  test('GET /api/jobs/:id returns job state', async () => {
    const j = registry.create({ videoId: 'x', sourceFile: 'x.mp4' });
    registry.update(j.id, { state: 'running' });
    const res = await request(app).get(`/api/jobs/${j.id}`);
    expect(res.status).toBe(200);
    expect(res.body.state).toBe('running');
  });

  test('GET /api/jobs/:id returns 404 when unknown', async () => {
    const res = await request(app).get('/api/jobs/unknown-id');
    expect(res.status).toBe(404);
  });

  test('GET /api/sources reflects activeJobId', async () => {
    const j = registry.create({ videoId: 'movie', sourceFile: 'movie.mp4' });
    const res = await request(app).get('/api/sources');
    expect(res.body[0].activeJobId).toBe(j.id);
  });
});
