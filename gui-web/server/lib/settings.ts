// library_settings.py 相当: ライブラリパスの永続化
import { readFileSync, writeFileSync, existsSync, mkdirSync, renameSync, statSync } from 'fs';
import { dirname, join } from 'path';
import { homedir } from 'os';

const SETTINGS_FILE =
  process.env.HLS_SETTINGS_FILE ??
  join(homedir(), '.config', 'hls-video-player', 'settings.json');

let cached: { library_root?: string } | null = null;

function loadFile(): { library_root?: string } {
  if (cached) return cached;
  if (!existsSync(SETTINGS_FILE)) {
    cached = {};
    return cached;
  }
  try {
    cached = JSON.parse(readFileSync(SETTINGS_FILE, 'utf-8') || '{}');
  } catch {
    cached = {};
  }
  return cached!;
}

export function getLibraryRoot(): string {
  const data = loadFile();
  if (data.library_root) return data.library_root;
  return process.env.LIBRARY_ROOT ?? './library';
}

export function setLibraryRoot(p: string): string {
  mkdirSync(dirname(SETTINGS_FILE), { recursive: true });
  const tmp = SETTINGS_FILE + '.tmp';
  writeFileSync(tmp, JSON.stringify({ library_root: p }, null, 2));
  renameSync(tmp, SETTINGS_FILE);
  cached = null;
  return p;
}

export function validateLibraryRoot(p: string): { ok: boolean; message: string } {
  if (!p) return { ok: false, message: 'パスが空です' };
  if (!existsSync(p)) return { ok: false, message: `パスが存在しません: ${p}` };
  try {
    if (!statSync(p).isDirectory()) {
      return { ok: false, message: `ディレクトリではありません: ${p}` };
    }
  } catch (e) {
    return { ok: false, message: `アクセスできません: ${p}` };
  }
  return { ok: true, message: `OK: ${p}` };
}

export function convertedDirName(): string {
  return process.env.CONVERTED_DIR ?? 'converted';
}
