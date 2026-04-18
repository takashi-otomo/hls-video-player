#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { convertMp4ToHls } = require('../src/utils/hlsConverter');
const { generateSprite } = require('../src/utils/spriteGenerator');

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.error('Usage: node scripts/convert.js <input.mp4> [videoId]');
    process.exit(1);
  }
  const inputPath = path.resolve(args[0]);
  if (!fs.existsSync(inputPath)) {
    console.error(`Input not found: ${inputPath}`);
    process.exit(1);
  }
  const videoId = args[1] || path.basename(inputPath, path.extname(inputPath))
    .replace(/[^a-zA-Z0-9_-]/g, '_');

  const mediaRoot = process.env.MEDIA_ROOT || path.resolve(__dirname, '../../media');
  const hlsOutDir = path.join(mediaRoot, 'hls', videoId);
  const spritesOutDir = path.join(mediaRoot, 'sprites');

  console.log(`→ Converting "${inputPath}" as id "${videoId}"`);
  console.log(`  HLS output:    ${hlsOutDir}`);
  console.log(`  Sprite output: ${spritesOutDir}`);

  console.log('\n[1/2] Generating HLS variants…');
  await convertMp4ToHls({ inputPath, outputDir: hlsOutDir });
  console.log('  ✓ HLS generated');

  console.log('\n[2/2] Generating sprite + WebVTT…');
  const { meta } = await generateSprite({ inputPath, outputDir: spritesOutDir, videoId });
  console.log(`  ✓ Sprite generated (${meta.tileCount} tiles, duration=${meta.duration.toFixed(1)}s)`);

  console.log(`\nDone. Restart the server and open: /player.html?id=${videoId}`);
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
