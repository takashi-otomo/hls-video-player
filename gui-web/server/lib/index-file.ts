// converted_index.py 相当: hls-index.json の読み込み (レガシー名フォールバック付き)
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot, convertedDirName } from './settings';

const INDEX_FILENAME = 'hls-index.json';
const LEGACY_FILENAMES = ['.hls-index.json', '.index.json'];
const INDEX_VERSION = 1;

export interface IndexData {
  version: number;
  completed: Record<string, {
    size?: number;
    mtime?: number;
    completed_at?: string;
    source?: string;
  }>;
}

function emptyIndex(): IndexData {
  return { version: INDEX_VERSION, completed: {} };
}

function indexPath(): string {
  return join(getLibraryRoot(), convertedDirName(), INDEX_FILENAME);
}

function legacyPaths(): string[] {
  const base = join(getLibraryRoot(), convertedDirName());
  return LEGACY_FILENAMES.map((n) => join(base, n));
}

function readJsonOrNull(p: string): IndexData | null {
  if (!existsSync(p)) return null;
  try {
    const data = JSON.parse(readFileSync(p, 'utf-8') || '{}');
    if (data.version !== INDEX_VERSION) return null;
    if (typeof data.completed !== 'object' || data.completed === null) return null;
    return data as IndexData;
  } catch {
    return null;
  }
}

export function loadIndex(): IndexData {
  const cur = readJsonOrNull(indexPath());
  if (cur) return cur;
  for (const lp of legacyPaths()) {
    const legacy = readJsonOrNull(lp);
    if (legacy) return legacy;
  }
  return emptyIndex();
}

export function indexedStems(): Set<string> {
  return new Set(Object.keys(loadIndex().completed));
}
