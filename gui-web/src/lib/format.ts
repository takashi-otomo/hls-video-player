export function formatDuration(s: number): string {
  s = Math.max(0, Math.floor(Number(s) || 0));
  if (!s) return '—';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function formatSize(bytes: number): string {
  let v = Number(bytes) || 0;
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (v < 1024) return `${v.toFixed(1)} ${unit}`;
    v /= 1024;
  }
  return `${v.toFixed(1)} TB`;
}
