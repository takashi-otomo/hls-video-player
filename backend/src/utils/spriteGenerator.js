const fs = require('fs');
const path = require('path');
const { runFfmpeg, probeDurationSeconds } = require('./ffmpegRunner');
const { generateVttContent } = require('./vttBuilder');

async function generateSprite({
  inputPath,
  outputDir,
  videoId,
  intervalSeconds = 10,
  tileWidth = 160,
  tileHeight = 90,
  columns = 10,
  rows = 10,
}) {
  fs.mkdirSync(outputDir, { recursive: true });

  const duration = await probeDurationSeconds(inputPath);
  const totalTiles = Math.max(1, Math.ceil(duration / intervalSeconds));
  const tilesPerSheet = columns * rows;
  const sheetCount = Math.ceil(totalTiles / tilesPerSheet);

  const spriteFilename = sheetCount === 1 ? `${videoId}.jpg` : `${videoId}-%d.jpg`;
  const spritePath = path.join(outputDir, spriteFilename);

  const args = [
    '-y',
    '-i', inputPath,
    '-vf', `fps=1/${intervalSeconds},scale=${tileWidth}:${tileHeight}:force_original_aspect_ratio=decrease,pad=${tileWidth}:${tileHeight}:(ow-iw)/2:(oh-ih)/2,tile=${columns}x${rows}`,
    '-an',
    '-vsync', 'vfr',
    '-qscale:v', '4',
  ];
  if (sheetCount > 1) args.push('-f', 'image2');
  args.push(spritePath);

  await runFfmpeg(args);

  const spriteUrl = `/sprites/${videoId}.jpg`;
  const vttContent = generateVttContent({
    spriteUrl,
    tileCount: totalTiles,
    tileWidth,
    tileHeight,
    columns,
    intervalSeconds,
  });
  const vttPath = path.join(outputDir, `${videoId}.vtt`);
  fs.writeFileSync(vttPath, vttContent);

  const metaPath = path.join(outputDir, `${videoId}.json`);
  const meta = {
    videoId,
    duration,
    tileCount: totalTiles,
    tileWidth,
    tileHeight,
    columns,
    rows,
    interval: intervalSeconds,
    sheetCount,
  };
  fs.writeFileSync(metaPath, JSON.stringify(meta, null, 2));

  return { spritePath, vttPath, metaPath, meta };
}

module.exports = { generateSprite };
