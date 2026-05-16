export interface Video {
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

export interface Settings {
  library_root: string;
  exists: boolean;
}

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

export interface TsStatus {
  folder: string;
  scanned_at: string;
  entries: TsEntry[];
  counts: Record<string, number>;
}

export interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  started_at?: string;
  finished_at?: string;
  progress?: number;
  error?: string;
}
