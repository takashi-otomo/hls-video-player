// favorites.py 相当: お気に入りの永続化 ({library_root}/favorites.json)
import { readFileSync, writeFileSync, existsSync, renameSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot } from './settings';

interface FavoritesFile {
  favorites?: string[];
}

function favoritesPath(): string {
  return join(getLibraryRoot(), 'favorites.json');
}

export function loadFavorites(): Set<string> {
  const p = favoritesPath();
  if (!existsSync(p)) return new Set();
  try {
    const data: FavoritesFile = JSON.parse(readFileSync(p, 'utf-8') || '{}');
    return new Set((data.favorites ?? []).filter(Boolean));
  } catch {
    return new Set();
  }
}

export function saveFavorites(favs: Set<string>): void {
  const p = favoritesPath();
  const tmp = p + '.tmp';
  const body = JSON.stringify({ favorites: Array.from(favs).sort() }, null, 2);
  try {
    writeFileSync(tmp, body);
    renameSync(tmp, p);
  } catch {
    // Drive FUSE で atomic rename が失敗するケースの fallback
    writeFileSync(p, body);
  }
}

export function isFavorite(id: string): boolean {
  return loadFavorites().has(id);
}

export function toggleFavorite(id: string): boolean {
  const favs = loadFavorites();
  let next: boolean;
  if (favs.has(id)) {
    favs.delete(id);
    next = false;
  } else {
    favs.add(id);
    next = true;
  }
  saveFavorites(favs);
  return next;
}

export function setFavorite(id: string, favorited: boolean): boolean {
  const favs = loadFavorites();
  if (favorited) favs.add(id);
  else favs.delete(id);
  saveFavorites(favs);
  return favorited;
}
