// library_catalog.py 相当: converted/ を走査して動画メタを返す
import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import { extname } from 'path';
import { loadFavorites } from './favorites';
import {
  driveConverted,
  mirrorConverted,
  resolveConverted,
  convertedExists,
} from './hybrid';

const THUMB_PERCENTS = [5, 30, 50, 60, 80];
const LIBRARY_URL_PREFIX = '/library';

export interface VideoEntry {
  id: string;
  title: string;
  duration: number;
  width: number;
  height: number;
  container: string;
  codec: string;
  formatLabel: string;
  isFavorite: boolean;
  masterUrl: string;
  posterUrl: string;
  thumbs: Array<{ percent: number; url: string }>;
}

function thumbFilename(p: number): string {
  return `thumb_${String(p).padStart(2, '0')}.jpg`;
}

function stemUrl(stem: string, rel: string): string {
  return `${LIBRARY_URL_PREFIX}/${encodeURIComponent(stem)}/${rel}`;
}


function formatLabel(sourceFilename: string, codec: string): string {
  const parts: string[] = [];
  const ext = extname(sourceFilename || '').replace('.', '').toUpperCase();
  if (ext) parts.push(ext);
  const c = (codec || '').trim().toLowerCase();
  const map: Record<string, string> = {
    h264: 'H.264',
    hevc: 'HEVC',
    h265: 'HEVC',
    vp9: 'VP9',
    av1: 'AV1',
    mpeg4: 'MPEG-4',
    mpeg2video: 'MPEG-2',
  };
  if (c) parts.push(map[c] ?? c.toUpperCase());
  return parts.join(' / ');
}

// メタキャッシュ: stem -> { entry, mtimeMs }
const metaCache = new Map<string, { entry: VideoEntry; mtimeMs: number }>();

function entryForStem(stem: string, favorites: Set<string>): VideoEntry | null {
  // 各ファイルはミラー優先で解決 (無ければ Drive パス)
  const masterPath = resolveConverted(`${stem}/hls/master.m3u8`);
  const posterPath = resolveConverted(`${stem}/thumbs/poster.png`);
  const metaPath = resolveConverted(`${stem}/meta.json`);

  if (!existsSync(masterPath) || !existsSync(posterPath) || !existsSync(metaPath)) {
    return null;
  }

  let mtimeMs = 0;
  try {
    mtimeMs = statSync(metaPath).mtimeMs;
  } catch {
    return null;
  }

  const cached = metaCache.get(stem);
  if (cached && cached.mtimeMs === mtimeMs) {
    // favorites だけ最新化して返す
    cached.entry.isFavorite = favorites.has(stem);
    return cached.entry;
  }

  let meta: any;
  try {
    meta = JSON.parse(readFileSync(metaPath, 'utf-8') || '{}');
  } catch {
    return null;
  }

  const framesMeta: Array<{ percent: number; file: string }> =
    meta?.thumbs?.frames ??
    THUMB_PERCENTS.map((p) => ({ percent: p, file: `thumbs/${thumbFilename(p)}` }));

  const thumbs: Array<{ percent: number; url: string }> = [];
  for (const f of framesMeta) {
    if (!f.file) continue;
    if (!convertedExists(`${stem}/${f.file}`)) continue;
    thumbs.push({ percent: Number(f.percent) || 0, url: stemUrl(stem, f.file) });
  }

  const sourceFilename = meta.source_filename || stem;
  const codec = meta.codec || '';

  const entry: VideoEntry = {
    id: stem,
    title: sourceFilename,
    duration: Number(meta.duration) || 0,
    width: Number(meta.width) || 0,
    height: Number(meta.height) || 0,
    container: extname(sourceFilename).replace('.', '').toLowerCase(),
    codec,
    formatLabel: formatLabel(sourceFilename, codec),
    isFavorite: favorites.has(stem),
    masterUrl: stemUrl(stem, 'hls/master.m3u8'),
    posterUrl: stemUrl(stem, 'thumbs/poster.png'),
    thumbs,
  };

  metaCache.set(stem, { entry, mtimeMs });
  return entry;
}

function readdirSafe(dir: string | null): string[] {
  if (!dir || !existsSync(dir)) return [];
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

export function listVideos(): VideoEntry[] {
  const favorites = loadFavorites();
  // 列挙は Drive (stat/readdir は EDEADLK しない) とミラーの和集合。
  // Drive が一覧を返せなくてもミラー側だけで表示できる。
  const names = new Set<string>([
    ...readdirSafe(driveConverted()),
    ...readdirSafe(mirrorConverted()),
  ]);
  const out: VideoEntry[] = [];
  for (const name of [...names].sort()) {
    if (name.startsWith('.')) continue;
    const entry = entryForStem(name, favorites);
    if (entry) out.push(entry);
  }
  return out;
}

export function getVideo(id: string): VideoEntry | null {
  const favorites = loadFavorites();
  return entryForStem(id, favorites);
}
