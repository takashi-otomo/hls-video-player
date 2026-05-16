// グローバル・バックグラウンド・ウォーマー
//
// 目的:
//  - 「強制読み込み (リトライ)」をコンポーネント寿命から切り離す。
//    Card / HlsPlayer がアンマウントされ、ページ遷移しても、登録済みの
//    URL のリトライ (= サーバのキャッシュ/ミラー反映待ち) は継続する。
//  - ただし全体の実行量を 1 つのスケジューラ + 同時実行上限で管理し、
//    多数の独立タイマで CPU/ネットワークを埋め尽くさない。
//
// 実体は「モジュールシングルトン」。SPA(ハッシュルータ)はページを
// リロードしないのでモジュール状態は遷移をまたいで生存する。
import { writable } from 'svelte/store';

// 同時に走らせる fetch の上限 (これがCPU/ネット使用量の主な制御点)。
const MAX_CONCURRENCY = 2;
// スケジューラの周期。
const TICK_MS = 500;
// バックオフ (失敗時): 3s から倍々、上限 20s。
const BACKOFF_BASE = 3000;
const BACKOFF_MAX = 20000;
// manifest は一度読めても再生成功まで一定間隔で再通知する。
const MANIFEST_STEADY_MS = 8000;

type Kind = 'image' | 'manifest';

interface Item {
  url: string;
  kind: Kind;
  attempts: number;
  nextAt: number;
  inflight: boolean;
}

const items = new Map<string, Item>();
const available = new Set<string>();
let active = 0;
let timer: ReturnType<typeof setInterval> | null = null;

// 何か状態が変わるたびに bump。コンポーネントはこれを購読して
// 「自分が待っている URL が available になったか」を判定する。
const tick = writable(0);
export const warmTick = { subscribe: tick.subscribe };
function bump() {
  tick.update((n) => n + 1);
}

export function isAvailable(url: string): boolean {
  return available.has(url);
}

/** url をウォーム対象に登録 (既にあれば何もしない=バックオフ維持) */
export function warm(url: string, kind: Kind = 'image'): void {
  if (!items.has(url)) {
    items.set(url, { url, kind, attempts: 0, nextAt: Date.now(), inflight: false });
  }
  ensureRunning();
}

/** 不要になった url を解放 (取得成功してもう待つ必要が無い等) */
export function release(url: string): void {
  items.delete(url);
  available.delete(url);
}

function ensureRunning() {
  if (timer) return;
  timer = setInterval(pump, TICK_MS);
  pump();
}

function pump() {
  if (items.size === 0 && active === 0) {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    return;
  }
  const now = Date.now();
  for (const item of items.values()) {
    if (active >= MAX_CONCURRENCY) break;
    if (item.inflight || item.nextAt > now) continue;
    item.inflight = true;
    active += 1;
    void fetchOne(item);
  }
}

async function fetchOne(item: Item) {
  try {
    const sep = item.url.includes('?') ? '&' : '?';
    const res = await fetch(`${item.url}${sep}w=${item.attempts + 1}`, {
      cache: 'reload',
    });
    if (res.ok) {
      // body を読み切ってサーバ側キャッシュ確定 + コネクション解放
      await res.arrayBuffer().catch(() => {});
      available.add(item.url);
      if (item.kind === 'image') {
        // 画像は一度読めれば完了 (キャッシュ済み)。キューから外す。
        items.delete(item.url);
      } else {
        // manifest は再生成功まで定期的に再通知 (player が再 load する)
        item.attempts = 0;
        item.nextAt = Date.now() + MANIFEST_STEADY_MS;
        item.inflight = false;
      }
      bump();
      return;
    }
    requeue(item); // 404 等 (ミラー未到達/Drive EDEADLK)
  } catch {
    requeue(item);
  } finally {
    active -= 1;
    if (item.kind === 'manifest' && items.has(item.url)) item.inflight = false;
  }
}

function requeue(item: Item) {
  item.attempts += 1;
  const delay =
    Math.min(BACKOFF_MAX, BACKOFF_BASE * 2 ** Math.min(item.attempts, 4)) +
    Math.random() * 800;
  item.nextAt = Date.now() + delay;
  item.inflight = false;
  available.delete(item.url);
}
