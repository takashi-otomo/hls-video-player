const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { listVideos } = require('./utils/videoCatalog');

function createApp({ mediaRoot, frontendRoot } = {}) {
  const app = express();
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
