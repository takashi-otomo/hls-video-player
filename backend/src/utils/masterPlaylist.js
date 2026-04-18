function buildMasterPlaylist(variants) {
  if (!Array.isArray(variants) || variants.length === 0) {
    throw new Error('variants must be a non-empty array');
  }
  const lines = ['#EXTM3U', '#EXT-X-VERSION:3'];
  for (const v of variants) {
    lines.push(`#EXT-X-STREAM-INF:BANDWIDTH=${v.bandwidth},RESOLUTION=${v.resolution}`);
    lines.push(v.playlist);
  }
  return lines.join('\n') + '\n';
}

module.exports = { buildMasterPlaylist };
