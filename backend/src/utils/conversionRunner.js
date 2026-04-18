const path = require('path');
const fs = require('fs');
const { convertMp4ToHls } = require('./hlsConverter');
const { generateSprite } = require('./spriteGenerator');

// ジョブ登録から実 FFmpeg 実行までを繋ぐ薄いラッパー。
// registry にステージ遷移を書き込むことで /api/jobs/:id のポーリング結果が更新される。
async function runConversion({ registry, jobId, mediaRoot, sourceFile, videoId }) {
  const inputPath = path.join(mediaRoot, 'source', sourceFile);
  const hlsDir = path.join(mediaRoot, 'hls', videoId);
  const spritesDir = path.join(mediaRoot, 'sprites');

  if (!fs.existsSync(inputPath)) {
    registry.update(jobId, { state: 'failed', error: `source not found: ${sourceFile}` });
    return;
  }

  try {
    registry.update(jobId, { state: 'running', stage: 'hls' });
    await convertMp4ToHls({ inputPath, outputDir: hlsDir });

    registry.update(jobId, { stage: 'sprite' });
    await generateSprite({ inputPath, outputDir: spritesDir, videoId });

    registry.update(jobId, { state: 'completed', stage: 'done' });
  } catch (err) {
    registry.update(jobId, {
      state: 'failed',
      error: String(err && err.message ? err.message : err).slice(0, 500),
    });
    // 中途半端な HLS 出力はクリーンアップ（次回再試行を可能にする）
    if (fs.existsSync(hlsDir) && !fs.existsSync(path.join(hlsDir, 'master.m3u8'))) {
      fs.rmSync(hlsDir, { recursive: true, force: true });
    }
  }
}

module.exports = { runConversion };
