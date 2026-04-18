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

    const spriteJpg = path.join(spritesRoot, `${id}.jpg`);
    const spriteVtt = path.join(spritesRoot, `${id}.vtt`);
    const spriteJson = path.join(spritesRoot, `${id}.json`);
    let sprite = null;
    if (fs.existsSync(spriteJpg) && fs.existsSync(spriteJson)) {
      const meta = JSON.parse(fs.readFileSync(spriteJson, 'utf8'));
      sprite = {
        url: `/sprites/${id}.jpg`,
        vttUrl: fs.existsSync(spriteVtt) ? `/sprites/${id}.vtt` : null,
        tileWidth: meta.tileWidth,
        tileHeight: meta.tileHeight,
        columns: meta.columns,
        interval: meta.interval,
      };
    }

    videos.push({
      id,
      title: id,
      masterUrl: `/hls/${id}/master.m3u8`,
      sprite,
    });
  }

  return videos;
}

module.exports = { listVideos };
