const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { listVideos } = require('./utils/videoCatalog');
const { listSources, resolveVideoId, VIDEO_EXTS } = require('./utils/sourceCatalog');
const { createJobRegistry } = require('./utils/jobRegistry');
const { runConversion } = require('./utils/conversionRunner');

function createApp({ mediaRoot, frontendRoot, registry, runner = runConversion } = {}) {
  const app = express();
  const jobs = registry || createJobRegistry();
  app.use(cors());
  app.use(express.json());

  app.get('/api/health', (_req, res) => {
    res.json({ status: 'ok', uptime: process.uptime() });
  });

  app.get('/api/videos', (_req, res) => {
    res.json(listVideos(mediaRoot));
  });

  app.get('/api/videos/:id', (req, res) => {
    const video = listVideos(mediaRoot).find((v) => v.id === req.params.id);
    if (!video) return res.status(404).json({ error: 'not_found' });
    res.json(video);
  });

  // --- Source files + conversion jobs ---
  app.get('/api/sources', (_req, res) => {
    const sources = listSources(mediaRoot).map((s) => {
      const active = jobs.findActiveByVideoId(s.videoId);
      return { ...s, activeJobId: active ? active.id : null };
    });
    res.json(sources);
  });

  app.post('/api/sources/:filename/convert', (req, res) => {
    const { filename } = req.params;
    const ext = path.extname(filename).toLowerCase();
    if (!VIDEO_EXTS.has(ext)) return res.status(400).json({ error: 'unsupported_extension' });

    const inputPath = path.join(mediaRoot, 'source', filename);
    // ディレクトリトラバーサル防御: 解決後のパスがソースディレクトリ配下であること
    const sourceRoot = path.resolve(path.join(mediaRoot, 'source'));
    if (!path.resolve(inputPath).startsWith(sourceRoot + path.sep)) {
      return res.status(400).json({ error: 'invalid_path' });
    }
    if (!fs.existsSync(inputPath)) return res.status(404).json({ error: 'not_found' });

    const videoId = resolveVideoId(filename);
    const alreadyConverted = fs.existsSync(path.join(mediaRoot, 'hls', videoId, 'master.m3u8'));
    if (alreadyConverted) return res.status(409).json({ error: 'already_converted', videoId });

    const active = jobs.findActiveByVideoId(videoId);
    if (active) return res.status(409).json({ error: 'already_running', jobId: active.id });

    const job = jobs.create({ videoId, sourceFile: filename });
    // 非同期にキック（レスポンスは即返す）
    setImmediate(() => {
      runner({ registry: jobs, jobId: job.id, mediaRoot, sourceFile: filename, videoId });
    });
    res.status(202).json({ jobId: job.id, videoId });
  });

  app.get('/api/jobs', (_req, res) => res.json(jobs.list()));

  app.get('/api/jobs/:id', (req, res) => {
    const job = jobs.get(req.params.id);
    if (!job) return res.status(404).json({ error: 'not_found' });
    res.json(job);
  });

  const hlsRoot = path.join(mediaRoot, 'hls');
  app.use('/hls', express.static(hlsRoot, {
    setHeaders: (res, filePath) => {
      if (filePath.endsWith('.m3u8')) {
        res.setHeader('Content-Type', 'application/vnd.apple.mpegurl');
        res.setHeader('Cache-Control', 'no-cache');
      } else if (filePath.endsWith('.ts')) {
        res.setHeader('Content-Type', 'video/mp2t');
        res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
      }
    },
  }));

  const spritesRoot = path.join(mediaRoot, 'sprites');
  if (fs.existsSync(spritesRoot)) {
    app.use('/sprites', express.static(spritesRoot, {
      setHeaders: (res, filePath) => {
        if (filePath.endsWith('.vtt')) {
          res.setHeader('Content-Type', 'text/vtt');
        }
      },
    }));
  }

  if (frontendRoot && fs.existsSync(frontendRoot)) {
    app.use('/', express.static(frontendRoot));
  }

  app.use((_req, res) => res.status(404).json({ error: 'not_found' }));

  return app;
}

module.exports = { createApp };
