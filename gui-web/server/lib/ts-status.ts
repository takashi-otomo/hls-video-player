// ts_merge_gui.py の scan_folder_with_index 相当 (Phase 2)
import { readdirSync, readFileSync, existsSync, statSync, unlinkSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot, convertedDirName } from './settings';

const PAT_NEW = /^(.+?)_(\d+)-(\d+)\.ts$/;          // name_1-3.ts
const PAT_OLD = /^(.+?)_part(\d+)\.ts$/;             // name_part01.ts
const PAT_SPLIT_MP4 = /^(.+?)_(\d+)\.mp4$/;          // name_1.mp4
const PAT_INDEX_URL = /https?:\/\/[^\s)]+\/posts\/([a-f0-9-]{36})/;

export interface TsEntry {
  uuid: string;
  url: string;
  status: string;
  part_count: number;
  total_size: number;
  complete: boolean;
  missing: number[];
  has_mp4: boolean;
  has_ts: boolean;
  split_mp4_count: number;
  hls: 'done' | 'none';
}

function indexPath(): string {
  return join(getLibraryRoot(), 'index.md');
}

function loadIndexEntries(): { uuid: string; url: string }[] {
  const p = indexPath();
  if (!existsSync(p)) return [];
  let text: string;
  try {
    text = readFileSync(p, 'utf-8');
  } catch {
    return [];
  }
  const out: { uuid: string; url: string }[] = [];
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(PAT_INDEX_URL);
    if (m) out.push({ uuid: m[1], url: m[0] });
  }
  return out;
}

interface Group {
  parts: { num: number; size: number }[];
  total: number | null;
  format: string;
  total_size: number;
  part_count: number;
  complete: boolean;
  missing: number[];
  merged_mp4: { exists: boolean; size: number };
  merged_ts: { exists: boolean; size: number };
  split_mp4s: { num: number; size: number }[];
}

function scanFolder(folder: string): Map<string, Group> {
  const groups = new Map<string, Group>();
  let names: string[];
  try {
    names = readdirSync(folder);
  } catch {
    return groups;
  }
  const sizeOf = (n: string): number => {
    try {
      return statSync(join(folder, n)).size;
    } catch {
      return 0;
    }
  };
  const ensure = (base: string): Group => {
    let g = groups.get(base);
    if (!g) {
      g = {
        parts: [],
        total: null,
        format: 'none',
        total_size: 0,
        part_count: 0,
        complete: true,
        missing: [],
        merged_mp4: { exists: false, size: 0 },
        merged_ts: { exists: false, size: 0 },
        split_mp4s: [],
      };
      groups.set(base, g);
    }
    return g;
  };

  for (const name of names) {
    let m = name.match(PAT_NEW);
    if (m) {
      const g = ensure(m[1]);
      g.format = 'new';
      g.total = Number(m[3]);
      g.parts.push({ num: Number(m[2]), size: sizeOf(name) });
      continue;
    }
    m = name.match(PAT_OLD);
    if (m) {
      const g = ensure(m[1]);
      g.format = 'old';
      g.parts.push({ num: Number(m[2]), size: sizeOf(name) });
      continue;
    }
    m = name.match(PAT_SPLIT_MP4);
    if (m) {
      const g = ensure(m[1]);
      g.split_mp4s.push({ num: Number(m[2]), size: sizeOf(name) });
    }
  }

  for (const [base, g] of groups) {
    g.parts.sort((a, b) => a.num - b.num);
    g.total_size = g.parts.reduce((s, p) => s + p.size, 0);
    g.part_count = g.parts.length;
    if (g.format === 'new' && g.total != null) {
      const actual = new Set(g.parts.map((p) => p.num));
      const missing: number[] = [];
      for (let i = 1; i <= g.total; i++) if (!actual.has(i)) missing.push(i);
      g.complete = missing.length === 0;
      g.missing = missing;
    }
    const mp4 = join(folder, `${base}.mp4`);
    const ts = join(folder, `${base}.ts`);
    if (existsSync(mp4)) g.merged_mp4 = { exists: true, size: sizeOf(`${base}.mp4`) };
    if (existsSync(ts)) g.merged_ts = { exists: true, size: sizeOf(`${base}.ts`) };
  }
  return groups;
}

function hlsStatus(uuid: string): 'done' | 'none' {
  const base = join(getLibraryRoot(), convertedDirName(), uuid);
  if (
    existsSync(join(base, 'hls', 'master.m3u8')) &&
    existsSync(join(base, 'thumbs', 'poster.png')) &&
    existsSync(join(base, 'meta.json'))
  ) {
    return 'done';
  }
  return 'none';
}

export function tsStatus(): {
  folder: string;
  scanned_at: string;
  entries: TsEntry[];
  counts: Record<string, number>;
} {
  const folder = getLibraryRoot();
  const idx = loadIndexEntries();
  const groups = scanFolder(folder);
  const seen = new Set<string>();
  const entries: TsEntry[] = [];

  const buildEntry = (uuid: string, url: string): TsEntry => {
    const g = groups.get(uuid);
    const hasMp4 = !!g?.merged_mp4.exists || (g?.split_mp4s.length ?? 0) > 0;
    const hasTs = !!g?.merged_ts.exists;
    const partCount = g?.part_count ?? 0;
    const complete = g?.complete ?? false;
    let status: string;
    if (hasMp4) status = partCount > 0 || hasTs ? 'MP4済(TS有)' : 'MP4済';
    else if (hasTs) status = 'TS済';
    else if (partCount === 0) status = '未DL';
    else if (!complete) status = '不完全';
    else status = '未結合';
    return {
      uuid,
      url,
      status,
      part_count: partCount,
      total_size: g?.total_size ?? 0,
      complete,
      missing: g?.missing ?? [],
      has_mp4: hasMp4,
      has_ts: hasTs,
      split_mp4_count: g?.split_mp4s.length ?? 0,
      hls: hlsStatus(uuid),
    };
  };

  for (const e of idx) {
    seen.add(e.uuid);
    entries.push(buildEntry(e.uuid, e.url));
  }
  for (const base of [...groups.keys()].sort()) {
    if (!seen.has(base)) entries.push(buildEntry(base, ''));
  }

  const counts: Record<string, number> = {
    mp4: 0,
    mp4_ts: 0,
    ts: 0,
    pending: 0,
    incomplete: 0,
    no_dl: 0,
  };
  const keyMap: Record<string, string> = {
    'MP4済': 'mp4',
    'MP4済(TS有)': 'mp4_ts',
    'TS済': 'ts',
    '未結合': 'pending',
    '不完全': 'incomplete',
    '未DL': 'no_dl',
  };
  for (const e of entries) {
    const k = keyMap[e.status];
    if (k) counts[k]++;
  }

  return {
    folder,
    scanned_at: new Date().toISOString(),
    entries,
    counts,
  };
}

export function addToIndex(urls: string[]): {
  added: number;
  skipped: number;
  invalid: number;
} {
  const p = indexPath();
  const existing = new Set<string>();
  let content = '';
  if (existsSync(p)) {
    content = readFileSync(p, 'utf-8');
    for (const line of content.split(/\r?\n/)) {
      const m = line.match(PAT_INDEX_URL);
      if (m) existing.add(m[1]);
    }
  }
  let added = 0,
    skipped = 0,
    invalid = 0;
  const newLines: string[] = [];
  for (const u of urls) {
    const m = u.match(PAT_INDEX_URL);
    if (!m) {
      invalid++;
      continue;
    }
    if (existing.has(m[1])) {
      skipped++;
      continue;
    }
    existing.add(m[1]);
    newLines.push(u.trim());
    added++;
  }
  if (added > 0) {
    const { writeFileSync } = require('fs');
    writeFileSync(p, newLines.join('\n') + '\n' + content);
  }
  return { added, skipped, invalid };
}

export function removeFromIndex(uuids: string[]): number {
  const p = indexPath();
  if (!existsSync(p)) return 0;
  const lines = readFileSync(p, 'utf-8').split(/\r?\n/);
  const target = new Set(uuids);
  let removed = 0;
  const kept = lines.filter((line) => {
    const m = line.match(PAT_INDEX_URL);
    if (m && target.has(m[1])) {
      removed++;
      return false;
    }
    return true;
  });
  if (removed > 0) {
    const { writeFileSync } = require('fs');
    writeFileSync(p, kept.join('\n'));
  }
  return removed;
}

// 指定 uuid の TS パート (<uuid>_*-N.ts / <uuid>_partNN.ts / <uuid>.ts) を削除
export function deleteTsParts(uuid: string): { deleted: number; freed: number } {
  const folder = getLibraryRoot();
  let names: string[];
  try {
    names = readdirSync(folder);
  } catch {
    return { deleted: 0, freed: 0 };
  }
  let deleted = 0;
  let freed = 0;
  for (const name of names) {
    let base: string | null = null;
    let m = name.match(PAT_NEW);
    if (m) base = m[1];
    else {
      m = name.match(PAT_OLD);
      if (m) base = m[1];
      else if (name === `${uuid}.ts`) base = uuid;
    }
    if (base !== uuid) continue;
    const fp = join(folder, name);
    try {
      const sz = statSync(fp).size;
      unlinkSync(fp);
      deleted++;
      freed += sz;
    } catch {
      /* skip */
    }
  }
  return { deleted, freed };
}
