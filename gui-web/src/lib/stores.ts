import { writable, derived } from 'svelte/store';
import type { Video, Settings } from './types';

export const videos = writable<Video[]>([]);
export const favoriteIds = writable<Set<string>>(new Set());
export const settings = writable<Settings | null>(null);
export const filterText = writable<string>('');
export const favoriteOnly = writable<boolean>(false);
export const videosLoaded = writable<boolean>(false);

export const filteredVideos = derived(
  [videos, favoriteIds, filterText, favoriteOnly],
  ([$videos, $favs, $text, $favOnly]) => {
    const q = $text.trim().toLowerCase();
    return $videos.filter((v) => {
      if ($favOnly && !$favs.has(v.id)) return false;
      if (q && !v.title.toLowerCase().includes(q) && !v.id.toLowerCase().includes(q))
        return false;
      return true;
    });
  },
);
