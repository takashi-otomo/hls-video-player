const fs = require('fs');
const path = require('path');
const { runFfmpeg } = require('./ffmpegRunner');
const { buildMasterPlaylist } = require('./masterPlaylist');

const DEFAULT_VARIANTS = [
  { name: '720p', height: 720, videoBitrate: '3000k', maxrate: '3600k', bufsize: '6000k', audioBitrate: '128k', crf: 26, resolution: '1280x720', bandwidth: 3000000 },
  { name: '480p', height: 480, videoBitrate: '1500k', maxrate: '1800k', bufsize: '3000k', audioBitrate: '128k', crf: 28, resolution: '854x480',  bandwidth: 1500000 },
  { name: '360p', height: 360, videoBitrate: '800k',  maxrate: '960k',  bufsize: '1600k', audioBitrate: '96k',  crf: 30, resolution: '640x360',  bandwidth: 800000 },
  { name: '240p', height: 240, videoBitrate: '400k',  maxrate: '480k',  bufsize: '800k',  audioBitrate: '64k',  crf: 32, resolution: '426x240',  bandwidth: 400000 },
];

function buildVariantArgs(variant, outDir, segmentSeconds, gop, { preset, threads }) {
  const scale = `scale=w=-2:h=${variant.height}:force_original_aspect_ratio=decrease:force_divisible_by=2`;
  const playlist = path.join(outDir, `${variant.name}.m3u8`);
  const segPattern = path.join(outDir, `${variant.name}_%03d.ts`);
  return [
    '-vf', scale,
    '-c:a', 'aac', '-ar', '48000', '-b:a', variant.audioBitrate,
    '-c:v', 'h264', '-profile:v', 'main',
    // CPU 抑制: preset は ultrafast→veryfast→faster→…→placebo の順で遅く＆画質向上。
    // veryfast は medium 比で CPU 約半分、サイズ増加 20% 程度のバランス。
    '-preset', preset,
    // 各エンコーダあたりのスレッド数上限。デフォルト 2 (= 4variant 並列時に最大 8 スレッド)。
    '-threads', String(threads),
    '-crf', String(variant.crf),
    // H.264 main profile は 4:2:0 のみ対応。ソースが 4:4:4 / 10bit でも安全に配信できるよう強制変換
    '-pix_fmt', 'yuv420p',
    '-sc_threshold', '0',
    '-g', String(gop), '-keyint_min', String(gop),
    '-hls_time', String(segmentSeconds),
    '-hls_playlist_type', 'vod',
    '-b:v', variant.videoBitrate, '-maxrate', variant.maxrate, '-bufsize', variant.bufsize,
    '-hls_segment_filename', segPattern,
    '-f', 'hls', playlist,
  ];
}

async function convertMp4ToHls({
  inputPath,
  outputDir,
  variants = DEFAULT_VARIANTS,
  segmentSeconds = 4,
  fps = 24,
  preset = process.env.FFMPEG_PRESET || 'veryfast',
  threads = parseInt(process.env.FFMPEG_THREADS || '2', 10),
  onProgress,
}) {
  fs.mkdirSync(outputDir, { recursive: true });
  const gop = segmentSeconds * fps * 0.5 * 2; // keep GOP aligned to segment (2 GOPs per segment by default)
  const gopSize = Math.max(2, Math.round(gop));

  const args = ['-y', '-i', inputPath];
  for (const v of variants) {
    args.push(...buildVariantArgs(v, outputDir, segmentSeconds, gopSize, { preset, threads }));
  }

  await runFfmpeg(args, { onProgress });

  const master = buildMasterPlaylist(
    variants.map((v) => ({
      bandwidth: v.bandwidth,
      resolution: v.resolution,
      playlist: `${v.name}.m3u8`,
    }))
  );
  const masterPath = path.join(outputDir, 'master.m3u8');
  fs.writeFileSync(masterPath, master);

  return { masterPath, variants: variants.map((v) => v.name) };
}

module.exports = { convertMp4ToHls, DEFAULT_VARIANTS, buildVariantArgs };
