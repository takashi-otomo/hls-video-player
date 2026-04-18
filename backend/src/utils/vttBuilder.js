function computeSpriteCoordinates(index, columns, tileWidth, tileHeight) {
  const x = (index % columns) * tileWidth;
  const y = Math.floor(index / columns) * tileHeight;
  return { x, y };
}

function formatTimestamp(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.floor(totalSeconds % 60);
  const ms = Math.round((totalSeconds - Math.floor(totalSeconds)) * 1000);
  const hh = String(hours).padStart(2, '0');
  const mm = String(minutes).padStart(2, '0');
  const ss = String(seconds).padStart(2, '0');
  const fff = String(ms).padStart(3, '0');
  return `${hh}:${mm}:${ss}.${fff}`;
}

function generateVttContent({ spriteUrl, tileCount, tileWidth, tileHeight, columns, intervalSeconds }) {
  const lines = ['WEBVTT', ''];
  for (let i = 0; i < tileCount; i++) {
    const start = i * intervalSeconds;
    const end = start + intervalSeconds;
    const { x, y } = computeSpriteCoordinates(i, columns, tileWidth, tileHeight);
    lines.push(String(i + 1));
    lines.push(`${formatTimestamp(start)} --> ${formatTimestamp(end)}`);
    lines.push(`${spriteUrl}#xywh=${x},${y},${tileWidth},${tileHeight}`);
    lines.push('');
  }
  return lines.join('\n');
}

module.exports = { computeSpriteCoordinates, formatTimestamp, generateVttContent };
