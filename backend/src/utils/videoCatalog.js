const fs = require('fs');
const path = require('path');

function listVideos(mediaRoot) {
  const hlsRoot = path.join(mediaRoot, 'hls');
  const spritesRoot = path.join(mediaRoot, 'sprites');
  if (!fs.existsSync(hlsRoot)) return [];

  const entries = fs.readdirSync(hlsRoot, { withFileTypes: true });
  const videos = [];

  for (const dirent of entries) {
    if (!dirent.isDirectory()) continue;
    const id = dirent.name;
    const masterPath = path.join(hlsRoot, id, 'master.m3u8');
    if (!fs.existsSync(masterPath)) continue;

    videos.push({
      id,
      title: id,
      masterUrl: `/hls/${id}/master.m3u8`,
      sprite: resolveSprite(spritesRoot, id),
    });
  }

  return videos;
}

// スプライトが単一シート (id.jpg) の場合も、複数シート (id-1.jpg, id-2.jpg, …) の
// 場合も同じ形で返す。フロントは sheets[] をタイル index から引いて切替表示する。
function resolveSprite(spritesRoot, id) {
  const spriteJson = path.join(spritesRoot, `${id}.json`);
  if (!fs.existsSync(spriteJson)) return null;

  let meta;
  try { meta = JSON.parse(fs.readFileSync(spriteJson, 'utf8')); }
  catch (_) { return null; }

  const sheets = [];
  const sheetCount = Math.max(1, meta.sheetCount || 1);

  if (sheetCount === 1) {
    const p = path.join(spritesRoot, `${id}.jpg`);
    if (fs.existsSync(p)) sheets.push(`/sprites/${id}.jpg`);
  } else {
    for (let i = 1; i <= sheetCount; i++) {
      const p = path.join(spritesRoot, `${id}-${i}.jpg`);
      if (fs.existsSync(p)) sheets.push(`/sprites/${id}-${i}.jpg`);
    }
  }

  if (sheets.length === 0) return null;

  const spriteVtt = path.join(spritesRoot, `${id}.vtt`);
  return {
    sheets,
    sheetCount: sheets.length,
    vttUrl: fs.existsSync(spriteVtt) ? `/sprites/${id}.vtt` : null,
    tileWidth: meta.tileWidth,
    tileHeight: meta.tileHeight,
    columns: meta.columns,
    rows: meta.rows || 10,
    interval: meta.interval,
    tileCount: meta.tileCount,
  };
}

module.exports = { listVideos, resolveSprite };
