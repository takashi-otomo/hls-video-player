const fs = require('fs');
const path = require('path');

const VIDEO_EXTS = new Set(['.mp4', '.mov', '.mkv', '.webm']);

function resolveVideoId(filename) {
  const base = path.basename(filename, path.extname(filename));
  return base.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function listSources(mediaRoot) {
  const sourceDir = path.join(mediaRoot, 'source');
  const hlsDir = path.join(mediaRoot, 'hls');
  if (!fs.existsSync(sourceDir)) return [];

  const entries = fs.readdirSync(sourceDir, { withFileTypes: true });
  const sources = [];

  for (const dirent of entries) {
    if (!dirent.isFile()) continue;
    const ext = path.extname(dirent.name).toLowerCase();
    if (!VIDEO_EXTS.has(ext)) continue;

    const fullPath = path.join(sourceDir, dirent.name);
    const stat = fs.statSync(fullPath);
    const videoId = resolveVideoId(dirent.name);
    const converted = fs.existsSync(path.join(hlsDir, videoId, 'master.m3u8'));

    sources.push({
      filename: dirent.name,
      videoId,
      sizeBytes: stat.size,
      modifiedAt: stat.mtime.toISOString(),
      converted,
    });
  }

  return sources.sort((a, b) => a.filename.localeCompare(b.filename));
}

module.exports = { listSources, resolveVideoId, VIDEO_EXTS };
