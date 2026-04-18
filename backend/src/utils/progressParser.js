// FFmpeg が stderr に出す `time=HH:MM:SS.mmm` を抽出し、duration と比較して 0-1 の進捗率を返すヘルパ。
const TIME_RE = /time=(\d+):(\d+):(\d+(?:\.\d+)?)/g;

function parseLatestTimestamp(text) {
  let last = null;
  let m;
  TIME_RE.lastIndex = 0;
  while ((m = TIME_RE.exec(text)) !== null) {
    last = m;
  }
  if (!last) return null;
  const h = parseInt(last[1], 10);
  const mm = parseInt(last[2], 10);
  const s = parseFloat(last[3]);
  if (Number.isNaN(h) || Number.isNaN(mm) || Number.isNaN(s)) return null;
  return h * 3600 + mm * 60 + s;
}

function computeRatio(currentSeconds, durationSeconds) {
  if (!durationSeconds || durationSeconds <= 0) return null;
  if (currentSeconds == null || currentSeconds < 0) return 0;
  return Math.max(0, Math.min(1, currentSeconds / durationSeconds));
}

// stderr チャンクを逐次受け取り、進捗率が上がったときだけ onRatio(ratio, meta) を呼ぶ。
function createProgressParser({ durationSeconds, onRatio }) {
  let lastTime = -1;
  return (chunk) => {
    const t = parseLatestTimestamp(chunk);
    if (t == null) return;
    if (t <= lastTime) return;
    lastTime = t;
    const ratio = computeRatio(t, durationSeconds);
    if (ratio == null) return;
    try { onRatio(ratio, { currentTime: t }); } catch (_) { /* swallow UI errors */ }
  };
}

module.exports = { parseLatestTimestamp, computeRatio, createProgressParser };
