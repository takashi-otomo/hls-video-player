import { writable, derived, get } from 'svelte/store';
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

// --- サムネ読み込み進捗 ---
// thumbLoaded: 一度でもポスターが表示できた id (sticky。スクロールで
//   カードが unmount されても保持し、進捗が巻き戻らない)
// thumbLoading: いま読み込み試行中の id (mount 中・未完了)
export const thumbLoaded = writable<Set<string>>(new Set());
export const thumbLoading = writable<Set<string>>(new Set());

export function thumbStart(id: string) {
  if (get(thumbLoaded).has(id)) return;
  thumbLoading.update((s) => (s.has(id) ? s : new Set(s).add(id)));
}
export function thumbDone(id: string) {
  thumbLoaded.update((s) => (s.has(id) ? s : new Set(s).add(id)));
  thumbLoading.update((s) => {
    if (!s.has(id)) return s;
    const n = new Set(s);
    n.delete(id);
    return n;
  });
}
export function thumbStop(id: string) {
  // 読み込み未完了のまま unmount された (loaded にはしない)
  thumbLoading.update((s) => {
    if (!s.has(id)) return s;
    const n = new Set(s);
    n.delete(id);
    return n;
  });
}

export const thumbProgress = derived(
  [filteredVideos, thumbLoaded, thumbLoading],
  ([$fv, $loaded, $loading]) => {
    let loaded = 0;
    let loading = 0;
    const loadingTitles: string[] = [];
    for (const v of $fv) {
      if ($loaded.has(v.id)) loaded++;
      else if ($loading.has(v.id)) {
        loading++;
        if (loadingTitles.length < 12) loadingTitles.push(v.title);
      }
    }
    return { total: $fv.length, loaded, loading, loadingTitles };
  },
);
