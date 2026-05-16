# 06. Svelte フロントエンド設計

## 6.1 コンポーネント階層

```
App.svelte                                 ← ルート、ルーティング判定
├── Header.svelte                          ← トップバー (ライブラリパス表示、設定リンク)
├── Library.svelte                         ← グリッドビュー (Phase 1)
│   ├── FilterBar.svelte                   ← ★ お気に入りフィルタ + 文字列フィルタ
│   └── VirtualGrid.svelte                 ← 仮想スクロール
│       └── Card.svelte (× N)              ← カード
├── Player.svelte                          ← プレイヤーページ (Phase 1)
│   ├── PlayerTopbar.svelte                ← ← 前 / ★ / 次 → / ✕ 閉じる
│   └── HlsPlayer.svelte                   ← Video.js wrapper
├── Settings.svelte                        ← ライブラリパス設定
└── TsManage.svelte                        ← TS結合管理 (Phase 2)
    ├── EntryTable.svelte
    ├── AddUrlForm.svelte
    └── ConvertPanel.svelte
```

## 6.2 ルーティング

シンプルにハッシュベース or `svelte-spa-router` を使う。

```typescript
// gui-web/src/main.ts
import App from './App.svelte';
import './app.css';

new App({
  target: document.getElementById('app')!,
});
```

```svelte
<!-- gui-web/src/App.svelte -->
<script lang="ts">
  import Router from 'svelte-spa-router';
  import Library from './routes/Library.svelte';
  import Player from './routes/Player.svelte';
  import Settings from './routes/Settings.svelte';
  import TsManage from './routes/TsManage.svelte';
  import Header from './lib/Header.svelte';

  const routes = {
    '/':            Library,
    '/player/:id':  Player,
    '/settings':    Settings,
    '/ts-manage':   TsManage,
  };
</script>

<Header />
<main>
  <Router {routes} />
</main>
```

`bun add svelte-spa-router` で入れる。

## 6.3 状態管理 (Svelte ストア)

```typescript
// gui-web/src/lib/stores.ts
import { writable, derived } from 'svelte/store';
import type { Video, Settings } from './types';

export const videos = writable<Video[]>([]);
export const favoriteIds = writable<Set<string>>(new Set());
export const settings = writable<Settings | null>(null);
export const filterText = writable<string>('');
export const favoriteOnly = writable<boolean>(false);

// 派生: フィルタ適用後の動画
export const filteredVideos = derived(
  [videos, favoriteIds, filterText, favoriteOnly],
  ([$videos, $favs, $text, $favOnly]) => {
    return $videos.filter(v => {
      if ($favOnly && !$favs.has(v.id)) return false;
      if ($text && !v.title.toLowerCase().includes($text.toLowerCase())) return false;
      return true;
    });
  }
);
```

### API クライアント

```typescript
// gui-web/src/lib/api.ts
async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  videos:    ()       => jsonFetch<Video[]>('/api/videos'),
  video:     (id: string) => jsonFetch<Video>(`/api/videos/${encodeURIComponent(id)}`),
  favorites: ()       => jsonFetch<{ favorites: string[] }>('/api/favorites'),
  toggleFav: (id: string, favorited?: boolean) =>
    jsonFetch<{ id: string; isFavorite: boolean }>(
      `/api/favorites/${encodeURIComponent(id)}`,
      { method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ favorited })}
    ),
  getSettings: () => jsonFetch<{ library_root: string; exists: boolean }>('/api/settings'),
  setLibraryRoot: (p: string) =>
    jsonFetch<{ library_root: string }>(
      '/api/settings/library_root',
      { method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ library_root: p })}
    ),
};
```

## 6.4 Library.svelte (グリッド)

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { videos, favoriteIds, filteredVideos } from '../lib/stores';
  import { api } from '../lib/api';
  import VirtualGrid from '../lib/VirtualGrid.svelte';
  import Card from '../lib/Card.svelte';
  import FilterBar from '../lib/FilterBar.svelte';

  let loading = true;
  let error: string | null = null;

  onMount(async () => {
    try {
      const [vs, favs] = await Promise.all([api.videos(), api.favorites()]);
      videos.set(vs);
      favoriteIds.set(new Set(favs.favorites));
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  });
</script>

<FilterBar />

{#if loading}
  <div class="loading">読み込み中…</div>
{:else if error}
  <div class="error">エラー: {error}</div>
{:else}
  <div class="count">{$filteredVideos.length} 件</div>
  <VirtualGrid items={$filteredVideos} itemHeight={260} itemWidth={240}
               let:item>
    <Card video={item} />
  </VirtualGrid>
{/if}

<style>
  .loading, .error, .count { padding: 1rem; color: #8b93a1; }
  .error { color: #ff9595; }
</style>
```

## 6.5 VirtualGrid.svelte (仮想スクロール)

1280 件すべての DOM を作らず、可視範囲のみ描画する。自作コンポーネントとして:

```svelte
<script lang="ts">
  import { onMount, tick } from 'svelte';
  type T = $$Generic;
  export let items: T[];
  export let itemHeight: number;
  export let itemWidth: number;
  export let gap = 12;

  let container: HTMLDivElement;
  let scrollY = 0;
  let viewportH = 0;
  let viewportW = 0;
  let cols = 1;

  $: cols = Math.max(1, Math.floor((viewportW + gap) / (itemWidth + gap)));
  $: cellH = itemHeight + gap;
  $: rows = Math.ceil(items.length / cols);
  $: totalH = rows * cellH + gap;

  $: firstRow = Math.max(0, Math.floor((scrollY - cellH) / cellH));
  $: lastRow  = Math.min(rows, Math.ceil((scrollY + viewportH + cellH) / cellH));
  $: visible = (() => {
    const out: { item: T; row: number; col: number; key: number }[] = [];
    for (let r = firstRow; r < lastRow; r++) {
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        if (i >= items.length) break;
        out.push({ item: items[i], row: r, col: c, key: i });
      }
    }
    return out;
  })();

  function onScroll() { scrollY = container.scrollTop; }
  function onResize() {
    viewportH = container.clientHeight;
    viewportW = container.clientWidth;
  }

  onMount(() => {
    onResize();
    const ro = new ResizeObserver(onResize);
    ro.observe(container);
    return () => ro.disconnect();
  });
</script>

<div class="vgrid-viewport" bind:this={container} on:scroll={onScroll}>
  <div class="vgrid-canvas" style="height:{totalH}px">
    {#each visible as v (v.key)}
      <div class="vgrid-cell" style="
        transform: translate({v.col * (itemWidth + gap) + gap}px,
                             {v.row * cellH + gap}px);
        width: {itemWidth}px; height: {itemHeight}px;
      ">
        <slot item={v.item} />
      </div>
    {/each}
  </div>
</div>

<style>
  .vgrid-viewport { width: 100%; height: calc(100vh - 100px); overflow-y: auto; }
  .vgrid-canvas { position: relative; }
  .vgrid-cell { position: absolute; top: 0; left: 0; }
</style>
```

これで 1280 件あっても DOM に存在するのは可視 ~30 個だけ。

## 6.6 Card.svelte (カード)

ホバースライドショー + お気に入りトグルの本体。

```svelte
<script lang="ts">
  import type { Video } from '../lib/types';
  import { favoriteIds } from './stores';
  import { api } from './api';

  export let video: Video;

  let hovering = false;
  let idx = 0;
  let timer: any = null;
  let imgEl: HTMLImageElement;

  $: src = (() => {
    if (!hovering || idx === 0) return video.posterUrl;
    return video.thumbs[idx - 1]?.url ?? video.posterUrl;
  })();

  function onEnter() {
    hovering = true;
    // 全 6 枚を先読み (poster は既にロード済みなので 5 枚)
    video.thumbs.forEach(t => { const i = new Image(); i.src = t.url; });
    timer = setInterval(() => {
      idx = (idx + 1) % (video.thumbs.length + 1);  // poster + 5 枚
    }, 700);
  }
  function onLeave() {
    hovering = false;
    if (timer) { clearInterval(timer); timer = null; }
    idx = 0;
  }

  $: isFav = $favoriteIds.has(video.id);

  async function toggleFav(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    // 楽観的更新
    const next = !isFav;
    favoriteIds.update(s => {
      if (next) s.add(video.id); else s.delete(video.id);
      return new Set(s);
    });
    try {
      const r = await api.toggleFav(video.id, next);
      // サーバ確定で同期
      favoriteIds.update(s => {
        if (r.isFavorite) s.add(video.id); else s.delete(video.id);
        return new Set(s);
      });
    } catch {
      // ロールバック
      favoriteIds.update(s => {
        if (next) s.delete(video.id); else s.add(video.id);
        return new Set(s);
      });
    }
  }

  function formatDuration(s: number): string {
    s = Math.max(0, Math.floor(s));
    if (!s) return '—';
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = (n: number) => String(n).padStart(2, '0');
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }
</script>

<a class="card" href="#/player/{video.id}"
   on:mouseenter={onEnter} on:mouseleave={onLeave}>
  <div class="thumb-wrap">
    <img bind:this={imgEl} src={src} alt={video.title} loading="lazy" />
    <button class="fav-btn" class:on={isFav} on:click={toggleFav}>
      {isFav ? '★' : '☆'}
    </button>
  </div>
  <div class="body">
    <div class="title">{video.title}</div>
    <div class="meta">
      <span class="chip">⏱ {formatDuration(video.duration)}</span>
      {#if video.formatLabel}<span class="chip fmt">{video.formatLabel}</span>{/if}
    </div>
  </div>
</a>

<style>
  .card {
    display: flex; flex-direction: column;
    background: #1a1d24; border: 1px solid #272c36; border-radius: 6px;
    overflow: hidden; text-decoration: none; color: inherit;
    transition: border-color 0.12s, transform 0.12s;
    height: 100%;
  }
  .card:hover { border-color: #4aa8ff; }
  .thumb-wrap { position: relative; aspect-ratio: 16/9; background: #0a0c10; }
  .thumb-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .fav-btn {
    position: absolute; top: 6px; right: 6px;
    width: 30px; height: 30px; border-radius: 50%;
    background: rgba(0,0,0,0.55); color: #c8c8c8;
    border: none; font-size: 16px; cursor: pointer;
    transition: transform 0.1s, background 0.15s, color 0.15s;
  }
  .fav-btn:hover { background: rgba(0,0,0,0.85); color: #fff; transform: scale(1.1); }
  .fav-btn.on { color: #ffc857; background: rgba(0,0,0,0.7); }
  .body { padding: 0.5rem 0.6rem; flex: 1; min-height: 0; }
  .title {
    font-size: 0.8rem; font-family: "SF Mono", Menlo, monospace;
    line-height: 1.3; word-break: break-all;
    max-height: 2.6em; overflow: hidden;
  }
  .meta { display: flex; gap: 0.4rem; margin-top: 0.3rem; font-size: 0.7rem; color: #8b93a1; }
  .chip { background: #0e1117; border: 1px solid #272c36; padding: 1px 6px; border-radius: 999px; }
  .chip.fmt { font-family: "SF Mono", Menlo, monospace; }
</style>
```

## 6.7 FilterBar.svelte

```svelte
<script lang="ts">
  import { filterText, favoriteOnly } from './stores';
</script>

<div class="filter-bar">
  <label>
    <input type="checkbox" bind:checked={$favoriteOnly} />
    ★ お気に入りのみ
  </label>
  <input type="text" placeholder="絞り込み (ファイル名)…" bind:value={$filterText} />
</div>

<style>
  .filter-bar { padding: 0.5rem 0.75rem; display: flex; gap: 1rem; align-items: center; }
  input[type=text] { flex: 1; max-width: 400px; }
</style>
```

## 6.8 Player.svelte

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { videos, favoriteIds } from '../lib/stores';
  import { api } from '../lib/api';
  import HlsPlayer from '../lib/HlsPlayer.svelte';
  import { params } from 'svelte-spa-router';

  $: id = $params.id;
  $: video = $videos.find(v => v.id === id);

  // ids の前後を把握
  $: idx = $videos.findIndex(v => v.id === id);
  $: prevId = idx > 0 ? $videos[idx - 1].id : null;
  $: nextId = idx >= 0 && idx < $videos.length - 1 ? $videos[idx + 1].id : null;
  $: isFav = $favoriteIds.has(id ?? '');

  function go(target: string | null) {
    if (target) window.location.hash = `#/player/${target}`;
  }
  function close() {
    window.history.length > 1 ? window.history.back() : (window.location.hash = '#/');
  }

  // ロード時に /api/videos が空なら fetch
  onMount(async () => {
    if ($videos.length === 0) {
      const [vs, favs] = await Promise.all([api.videos(), api.favorites()]);
      videos.set(vs);
      favoriteIds.set(new Set(favs.favorites));
    }
  });

  async function toggleFav() {
    if (!id) return;
    const next = !isFav;
    favoriteIds.update(s => {
      if (next) s.add(id); else s.delete(id);
      return new Set(s);
    });
    await api.toggleFav(id, next);
  }

  // キーボードショートカット
  function onKey(e: KeyboardEvent) {
    if (e.target instanceof HTMLInputElement) return;
    if (e.key === 'ArrowLeft' && prevId) go(prevId);
    else if (e.key === 'ArrowRight' && nextId) go(nextId);
    else if (e.key === 'f' || e.key === 'F') toggleFav();
  }
</script>

<svelte:window on:keydown={onKey} />

<div class="player-root">
  <div class="topbar">
    <button disabled={!prevId} on:click={() => go(prevId)}>← 前</button>
    <button class="fav" class:on={isFav} on:click={toggleFav}>
      {isFav ? '★ お気に入り済' : '☆ お気に入り'}
    </button>
    <span class="title">{video?.title ?? id}</span>
    <button disabled={!nextId} on:click={() => go(nextId)}>次 →</button>
    <button class="close" on:click={close}>✕ 閉じる</button>
  </div>
  {#if video}
    <div class="wrap">
      <HlsPlayer {video} />
    </div>
  {/if}
</div>

<!-- スタイルは長いので省略。app/player_embed.py の CSS をベースに移植 -->
```

## 6.9 HlsPlayer.svelte

Video.js + VHS で HLS 再生。既存 `playerFactory.js` を Svelte 内でラップする。

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import videojs from 'video.js';
  import type { Video } from './types';
  import 'video.js/dist/video-js.css';

  export let video: Video;
  let mount: HTMLDivElement;
  let player: any = null;

  onMount(() => {
    const el = document.createElement('video-js');
    el.className = 'video-js vjs-default-skin vjs-big-play-centered';
    el.setAttribute('controls', '');
    el.setAttribute('preload', 'auto');
    if (video.posterUrl) el.setAttribute('poster', video.posterUrl);
    const src = document.createElement('source');
    src.src = video.masterUrl;
    src.type = 'application/x-mpegURL';
    el.appendChild(src);
    mount.appendChild(el);

    player = videojs(el, {
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      aspectRatio: '16:9',
      html5: { vhs: { overrideNative: true, enableLowInitialPlaylist: true }},
    });

    // 既存の seek-bar preview / quality selector ロジックを移植
    if (video.thumbs?.length) attachSeekbarPreview(player, video);
    attachQualitySelector(player);
  });

  onDestroy(() => {
    if (player) try { player.dispose(); } catch {}
  });
</script>

<div bind:this={mount} class="hls-mount"></div>

<style>
  .hls-mount { width: 100%; max-width: 1280px; margin: 0 auto; }
  :global(.video-js) { width: 100% !important; height: auto !important; }
</style>
```

`video.js` のインストール:
```bash
bun add video.js
```

## 6.10 Settings.svelte

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { settings } from '../lib/stores';

  let path = '';
  let message = '';
  let messageType: 'ok' | 'error' | '' = '';

  onMount(async () => {
    const s = await api.getSettings();
    settings.set(s);
    path = s.library_root;
  });

  async function save() {
    try {
      const r = await api.setLibraryRoot(path);
      message = `✅ 保存しました: ${r.library_root}`;
      messageType = 'ok';
      settings.set({ library_root: r.library_root, exists: true });
    } catch (e: any) {
      message = `❌ ${e.message}`;
      messageType = 'error';
    }
  }
</script>

<h2>ライブラリパス設定</h2>
<input type="text" bind:value={path} placeholder="/path/to/library" />
<button on:click={save}>保存して反映</button>
{#if message}<p class={messageType}>{message}</p>{/if}
```

## 6.11 CSS 戦略

CSS フレームワークは導入しない。理由:
- Tailwind は学習コスト & ビルド設定が増える
- 既存 Python GUI / Web /play のスタイルを移植したいだけ

`gui-web/src/app.css` にグローバル変数だけ定義:

```css
:root {
  --bg: #0a0c10;
  --surface: #1a1d24;
  --border: #272c36;
  --text: #e6e8eb;
  --muted: #8b93a1;
  --accent: #4aa8ff;
  --gold: #ffc857;
  --danger: #ff9595;
}

* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
button {
  font-family: inherit;
  background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 0.4rem 0.8rem; cursor: pointer;
}
button:hover:not(:disabled) { border-color: var(--accent); }
button:disabled { opacity: 0.4; cursor: not-allowed; }
input[type=text] {
  font-family: inherit;
  background: #0e1117; color: var(--text);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 0.4rem 0.6rem;
}
```

## 6.12 型定義

```typescript
// gui-web/src/lib/types.ts
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
```

## 6.13 ビルド設定

`vite.config.ts` で `assetsInlineLimit: 0` を指定すると base64 化されず HTTP/2 streaming で効率的に配信される。

`bun.lockb` は commit する (再現可能ビルド)。

`gui-web/package.json` の最小構成:
```json
{
  "name": "hls-gui",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "server": "bun run server/index.ts",
    "check": "svelte-check"
  },
  "dependencies": {
    "hono": "^4",
    "svelte-spa-router": "^4",
    "video.js": "^8"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^3",
    "@tsconfig/svelte": "^5",
    "@types/node": "^20",
    "svelte": "^4",
    "svelte-check": "^3",
    "typescript": "^5",
    "vite": "^5"
  }
}
```
