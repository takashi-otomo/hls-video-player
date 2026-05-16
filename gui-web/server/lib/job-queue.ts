// ファイルベース job queue: gui が spec を書き、converter コンテナが処理する
import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { getLibraryRoot } from './settings';

export interface JobSpec {
  id: string;
  type: 'hls' | 'ts-merge';
  created_at: string;
  params: Record<string, any>;
}

export interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  started_at?: string;
  finished_at?: string;
  progress?: number;
  error?: string;
  current_target?: string;
  stats?: Record<string, number>;
}

function jobsDir(): string {
  return join(getLibraryRoot(), '.jobs');
}

function newJobId(): string {
  const t = Date.now().toString(36).toUpperCase().padStart(10, '0');
  const r = Math.random().toString(36).slice(2, 10).toUpperCase();
  return `${t}${r}`;
}

export async function enqueue(
  spec: Omit<JobSpec, 'id' | 'created_at'>,
): Promise<JobSpec> {
  const dir = jobsDir();
  mkdirSync(dir, { recursive: true });
  const full: JobSpec = {
    id: newJobId(),
    created_at: new Date().toISOString(),
    ...spec,
  };
  writeFileSync(join(dir, `${full.id}.json`), JSON.stringify(full, null, 2));
  return full;
}

export function getStatus(jobId: string): JobStatus | null {
  const statusP = join(jobsDir(), `${jobId}.status.json`);
  const specP = join(jobsDir(), `${jobId}.json`);
  if (!existsSync(statusP)) {
    if (existsSync(specP)) return { id: jobId, state: 'queued' };
    return null;
  }
  try {
    return JSON.parse(readFileSync(statusP, 'utf-8'));
  } catch {
    return null;
  }
}

export function getLogPath(jobId: string): string {
  return join(jobsDir(), `${jobId}.log`);
}
