const path = require('path');
const fs = require('fs');
const { convertMp4ToHls } = require('./hlsConverter');
const { generateSprite } = require('./spriteGenerator');
const { probeDurationSeconds } = require('./ffmpegRunner');

// ステージの全体に対する重み（合計 1.0）。HLS 変換が圧倒的に重いので 85%、スプライトは 13%、
// 先頭 2% は probe（duration 取得）のブートストラップに割り当てる。
const STAGE_WEIGHTS = { probe: 0.02, hls: 0.83, sprite: 0.15 };

// ジョブ登録から実 FFmpeg 実行までを繋ぐラッパー。
// 各ステージの進捗を集約して job.progress (0..1) と job.stage を更新する。
// UI はこれをポーリングしてプログレスバーを描画する。
async function runConversion({ registry, jobId, mediaRoot, sourceFile, videoId }) {
  const inputPath = path.join(mediaRoot, 'source', sourceFile);
  const hlsDir = path.join(mediaRoot, 'hls', videoId);
  const spritesDir = path.join(mediaRoot, 'sprites');

  if (!fs.existsSync(inputPath)) {
    registry.update(jobId, { state: 'failed', error: `source not found: ${sourceFile}`, progress: 0 });
    return;
  }

  try {
    registry.update(jobId, { state: 'running', stage: 'probe', progress: 0 });
    const duration = await probeDurationSeconds(inputPath);
    registry.update(jobId, { progress: STAGE_WEIGHTS.probe, durationSeconds: duration });

    // --- HLS stage ---
    registry.update(jobId, { stage: 'hls' });
    await convertMp4ToHls({
      inputPath,
      outputDir: hlsDir,
      durationSeconds: duration,
      onProgress: (ratio) => {
        const overall = STAGE_WEIGHTS.probe + STAGE_WEIGHTS.hls * ratio;
        registry.update(jobId, { progress: clamp01(overall), stageProgress: ratio });
      },
    });
    registry.update(jobId, { progress: STAGE_WEIGHTS.probe + STAGE_WEIGHTS.hls, stageProgress: 1 });

    // --- Sprite stage ---
    registry.update(jobId, { stage: 'sprite', stageProgress: 0 });
    await generateSprite({
      inputPath,
      outputDir: spritesDir,
      videoId,
      durationSeconds: duration,
      onProgress: (ratio) => {
        const overall = STAGE_WEIGHTS.probe + STAGE_WEIGHTS.hls + STAGE_WEIGHTS.sprite * ratio;
        registry.update(jobId, { progress: clamp01(overall), stageProgress: ratio });
      },
    });

    registry.update(jobId, { state: 'completed', stage: 'done', progress: 1, stageProgress: 1 });
  } catch (err) {
    registry.update(jobId, {
      state: 'failed',
      error: String(err && err.message ? err.message : err).slice(0, 500),
    });
    if (fs.existsSync(hlsDir) && !fs.existsSync(path.join(hlsDir, 'master.m3u8'))) {
      fs.rmSync(hlsDir, { recursive: true, force: true });
    }
  }
}

function clamp01(v) { return Math.max(0, Math.min(1, v)); }

module.exports = { runConversion, STAGE_WEIGHTS };
