import type { Video, Settings, TsStatus, JobStatus } from './types';

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as any).error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => jsonFetch<{ ok: boolean; library_root: string }>('/api/health'),

  videos: () => jsonFetch<Video[]>('/api/videos'),
  video: (id: string) =>
    jsonFetch<Video>(`/api/videos/${encodeURIComponent(id)}`),

  favorites: () =>
    jsonFetch<{ favorites: string[] }>('/api/favorites'),
  toggleFav: (id: string, favorited?: boolean) =>
    jsonFetch<{ id: string; isFavorite: boolean }>(
      `/api/favorites/${encodeURIComponent(id)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ favorited }),
      },
    ),

  getSettings: () =>
    jsonFetch<Settings>('/api/settings'),
  setLibraryRoot: (p: string) =>
    jsonFetch<{ library_root: string; message: string }>(
      '/api/settings/library_root',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ library_root: p }),
      },
    ),

  // Phase 2
  tsStatus: () => jsonFetch<TsStatus>('/api/ts/status'),
  addToIndex: (urls: string[]) =>
    jsonFetch<{ ok: boolean; added: number; skipped: number; invalid: number }>(
      '/api/ts/index/add',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls }),
      },
    ),
  removeFromIndex: (uuids: string[]) =>
    jsonFetch<{ ok: boolean; removed: number }>(
      '/api/ts/index/remove',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uuids }),
      },
    ),
  deleteTsParts: (uuid: string) =>
    jsonFetch<{ ok: boolean; deleted: number; freed: number }>(
      `/api/ts/ts-parts/${encodeURIComponent(uuid)}`,
      { method: 'DELETE' },
    ),
  startConvert: (opts: {
    type: 'hls' | 'ts-merge';
    filter?: string;
    force?: boolean;
    workers?: number;
    delete?: boolean;
  }) =>
    jsonFetch<{ ok: boolean; job_id: string }>('/api/convert/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts),
    }),
  jobStatus: (id: string) =>
    jsonFetch<JobStatus>(`/api/convert/jobs/${encodeURIComponent(id)}`),
};
