<script lang="ts">
  import { onMount } from 'svelte';
  import { push } from 'svelte-spa-router';
  import { videos, favoriteIds, videosLoaded } from '../lib/stores';
  import { api } from '../lib/api';
  import HlsPlayer from '../lib/HlsPlayer.svelte';
  import type { Video } from '../lib/types';

  export let params: { id?: string } = {};
  $: id = params.id ? decodeURIComponent(params.id) : '';

  let single: Video | null = null;

  // 一覧が無い (直リンク等) 場合は単体取得
  onMount(async () => {
    if ($videos.length === 0 && id) {
      try {
        single = await api.video(id);
      } catch (e) {
        console.error('video load failed', e);
      }
    }
  });

  $: list = $videos;
  $: video = list.find((v) => v.id === id) ?? single;
  $: idx = list.findIndex((v) => v.id === id);
  $: prevId = idx > 0 ? list[idx - 1].id : null;
  $: nextId = idx >= 0 && idx < list.length - 1 ? list[idx + 1].id : null;
  $: isFav = $favoriteIds.has(id);

  function go(target: string | null) {
    if (target) push(`/player/${encodeURIComponent(target)}`);
  }
  function close() {
    if (window.history.length > 1) window.history.back();
    else push('/');
  }
  async function toggleFav() {
    if (!id) return;
    const next = !isFav;
    favoriteIds.update((s) => {
      const n = new Set(s);
      if (next) n.add(id);
      else n.delete(id);
      return n;
    });
    try {
      await api.toggleFav(id, next);
    } catch {
      favoriteIds.update((s) => {
        const n = new Set(s);
        if (next) n.delete(id);
        else n.add(id);
        return n;
      });
    }
  }

  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
    if (e.key === 'ArrowLeft' && prevId) go(prevId);
    else if (e.key === 'ArrowRight' && nextId) go(nextId);
    else if (e.key === 'f' || e.key === 'F') toggleFav();
    else if (e.key === 'Escape') close();
  }
</script>

<svelte:window on:keydown={onKey} />

<div class="player-root">
  <div class="topbar">
    <button class="nav" disabled={!prevId} on:click={() => go(prevId)}>← 前</button>
    <button class="fav" class:on={isFav} on:click={toggleFav}>
      {isFav ? '★ お気に入り済' : '☆ お気に入り'}
    </button>
    <span class="title" title={video?.title ?? id}>{video?.title ?? id}</span>
    <button class="nav" disabled={!nextId} on:click={() => go(nextId)}>次 →</button>
    <button class="close" on:click={close}>✕ 閉じる</button>
  </div>

  {#if video}
    <div class="wrap">
      {#key video.id}
        <HlsPlayer {video} />
      {/key}
    </div>
  {:else if !$videosLoaded}
    <div class="loading"><div class="spinner"></div>読み込み中…</div>
  {:else}
    <div class="error">動画が見つかりません: {id}</div>
  {/if}
</div>

<style>
  .player-root {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 50px);
    background: #000;
  }
  .topbar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .topbar .title {
    flex: 1;
    font-size: 0.85rem;
    font-family: "SF Mono", Menlo, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
  }
  .topbar .nav { color: var(--accent); }
  .topbar .fav {
    background: #2a2f3a;
    color: #c8d0dc;
  }
  .topbar .fav.on {
    background: #3d3320;
    color: var(--gold);
    border-color: var(--gold);
  }
  .topbar .close {
    background: #4a1f1f;
    color: #ffb3b3;
    border-color: #6a2c2c;
  }
  .topbar .close:hover { background: #5e2828; border-color: #d04444; }
  .wrap {
    flex: 1;
    min-height: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem;
  }
</style>
