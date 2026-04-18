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
