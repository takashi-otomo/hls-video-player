// ハイブリッド解決:
//   - 列挙(カタログ)は Drive を見る (stat/readdir は Docker+Drive でも動く)
//   - ファイル本文はローカルミラー (MIRROR_ROOT) にあればそこから、
//     無ければ Drive にフォールバック (Drive 本文 read は EDEADLK で
//     失敗しうるが、その場合はローディング表示。ミラーが進むと自動で
//     ローカル配信に切り替わる)
import { existsSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot, convertedDirName } from './settings';

function mirrorRoot(): string {
  return process.env.MIRROR_ROOT ?? '';
}

/** Drive 側の converted/ ルート */
export function driveConverted(): string {
  return join(getLibraryRoot(), convertedDirName());
}

/** ローカルミラーの converted/ ルート (未設定なら null) */
export function mirrorConverted(): string | null {
  const m = mirrorRoot();
  return m ? join(m, convertedDirName()) : null;
}

/**
 * converted/ 配下の相対パス rel (例: "<stem>/thumbs/poster.png") を
 * ミラー優先で実パスに解決する。ミラーに無ければ Drive パスを返す。
 */
export function resolveConverted(rel: string): string {
  const m = mirrorConverted();
  if (m) {
    const mp = join(m, rel);
    if (existsSync(mp)) return mp;
  }
  return join(driveConverted(), rel);
}

/** rel がミラー or Drive のどちらかに存在するか */
export function convertedExists(rel: string): boolean {
  const m = mirrorConverted();
  if (m && existsSync(join(m, rel))) return true;
  return existsSync(join(driveConverted(), rel));
}

/** rel がローカルミラーに存在するか (本文をローカル配信できるか) */
export function inMirror(rel: string): boolean {
  const m = mirrorConverted();
  return !!m && existsSync(join(m, rel));
}
