const { spawn } = require('child_process');
const os = require('os');

// CPU 抑制: FFMPEG_NICE が指定され、かつ非 Windows であれば `nice -n N ffmpeg …` で起動する。
// 優先度を下げることで対話操作や他プロセスへの影響を軽減（処理時間は微増）。
function buildInvocation(ffmpegPath, args) {
  const niceRaw = process.env.FFMPEG_NICE;
  const niceLevel = niceRaw !== undefined && niceRaw !== '' ? parseInt(niceRaw, 10) : NaN;
  if (!Number.isNaN(niceLevel) && os.platform() !== 'win32') {
    return { cmd: 'nice', cmdArgs: ['-n', String(niceLevel), ffmpegPath, ...args] };
  }
  return { cmd: ffmpegPath, cmdArgs: args };
}

function runFfmpeg(args, { ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg', onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const { cmd, cmdArgs } = buildInvocation(ffmpegPath, args);
    const proc = spawn(cmd, cmdArgs, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    proc.stderr.on('data', (chunk) => {
      const text = chunk.toString();
      stderr += text;
      if (onProgress) onProgress(text);
    });
    proc.on('error', reject);
    proc.on('close', (code) => {
      if (code === 0) resolve({ stderr });
      else reject(new Error(`ffmpeg exited with code ${code}\n${stderr}`));
    });
  });
}

function runFfprobeJson(args, { ffprobePath = process.env.FFPROBE_PATH || 'ffprobe' } = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(ffprobePath, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (c) => { stdout += c.toString(); });
    proc.stderr.on('data', (c) => { stderr += c.toString(); });
    proc.on('error', reject);
    proc.on('close', (code) => {
      if (code !== 0) return reject(new Error(`ffprobe exited with code ${code}\n${stderr}`));
      try {
        resolve(JSON.parse(stdout));
      } catch (err) {
        reject(err);
      }
    });
  });
}

async function probeDurationSeconds(inputPath) {
  const data = await runFfprobeJson([
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'json',
    inputPath,
  ]);
  return parseFloat(data.format?.duration ?? '0');
}

module.exports = { runFfmpeg, runFfprobeJson, probeDurationSeconds, buildInvocation };
