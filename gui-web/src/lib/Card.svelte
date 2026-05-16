<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import type { Video } from './types';
  import {
    favoriteIds,
    thumbStart,
    thumbDone,
    thumbStop,
  } from './stores';
  import { api } from './api';
  import { formatDuration } from './format';
  import { warm, release, isAvailable, warmTick } from './warmer';

  export let video: Video;

  let idx = 0;
  let timer: ReturnType<typeof setInterval> | null = null;

  $: seq = [video.posterUrl, ...video.thumbs.map((t) => t.url)];
  $: base = seq[idx] ?? video.posterUrl;
  $: isFav = $favoriteIds.has(video.id);

  // --- サムネ読み込み状態 ---
  // 404 (Drive 未ミラー等) でも「リンク切れ」ではなくローディング表示。
  // リトライはこのコンポーネントではなくグローバル warmer が担う:
  // ページ遷移/スクロールでカードが消えても warmer が裏でサーバ
  // キャッシュを温め続け、同時実行数も一元管理される (CPU を多数の
  // タイマで埋め尽くさない)。読めるようになったら再読込して表示。
  let ready = false;
  let bust = 0;
  let lastBase = '';

  $: if (base !== lastBase) {
    lastBase = base;
    ready = false;
    bust = 0;
  }
  // warmer が available にしたら bust を上げて <img> を貼り直す。
  $: if ($warmTick >= 0 && !ready && bust === 0 && isAvailable(base)) {
    bust = 1;
  }
  $: src = bust > 0 ? `${base}${base.includes('?') ? '&' : '?'}w=${bust}` : base;

  function onImgLoad() {
    ready = true;
    release(base); // もう warmer に温めさせる必要はない
    // idx===0 (ポスター) が表示できたらこの動画は「読込済」
    if (idx === 0) thumbDone(video.id);
  }
  function onImgError() {
    if (ready) return;
    // グローバル warmer に登録 (同時実行制限つきで裏で再試行継続)。
    // カードが unmount されても warmer はサーバキャッシュを温め続ける。
    warm(base, 'image');
  }

  function onEnter() {
    // 先読み
    video.thumbs.forEach((t) => {
      const i = new Image();
      i.src = t.url;
    });
    if (timer) clearInterval(timer);
    idx = 0;
    timer = setInterval(() => {
      idx = (idx + 1) % seq.length;
    }, 700);
  }
  function onLeave() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    idx = 0;
  }

  onMount(() => thumbStart(video.id));
  onDestroy(() => {
    if (timer) clearInterval(timer);
    // retry は warmer 側で継続させる (release しない=遷移後も温め続ける)
    thumbStop(video.id);
  });

  async function toggleFav(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const next = !isFav;
    favoriteIds.update((s) => {
      const n = new Set(s);
      if (next) n.add(video.id);
      else n.delete(video.id);
      return n;
    });
    try {
      const r = await api.toggleFav(video.id, next);
      favoriteIds.update((s) => {
        const n = new Set(s);
        if (r.isFavorite) n.add(video.id);
        else n.delete(video.id);
        return n;
      });
    } catch {
      favoriteIds.update((s) => {
        const n = new Set(s);
        if (next) n.delete(video.id);
        else n.add(video.id);
        return n;
      });
    }
  }
</script>

<a
  class="card"
  href="#/player/{encodeURIComponent(video.id)}"
  on:mouseenter={onEnter}
  on:mouseleave={onLeave}
>
  <div class="thumb-wrap">
    <img
      src={src}
      alt={video.title}
      loading="lazy"
      draggable="false"
      class:loaded={ready}
      on:load={onImgLoad}
      on:error={onImgError}
    />
    {#if !ready}
      <div class="thumb-loading" aria-label="読み込み中" title="読み込み中…">
        <div class="shimmer"></div>
        <div class="spinner"></div>
      </div>
    {/if}
    <button
      class="fav-btn"
      class:on={isFav}
      on:click={toggleFav}
      title={isFav ? 'お気に入り解除' : 'お気に入りに追加'}
      aria-pressed={isFav}
    >
      {isFav ? '★' : '☆'}
    </button>
  </div>
  <div class="body">
    <div class="title">{video.title}</div>
    <div class="meta">
      <span class="chip">⏱ {formatDuration(video.duration)}</span>
      {#if video.formatLabel}
        <span class="chip fmt">{video.formatLabel}</span>
      {/if}
    </div>
  </div>
</a>

<style>
  .card {
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    color: inherit;
    height: 100%;
    transition: border-color 0.12s, transform 0.12s;
  }
  .card:hover { border-color: var(--accent); }
  .thumb-wrap {
    position: relative;
    aspect-ratio: 16 / 9;
    background: var(--bg);
    flex-shrink: 0;
  }
  .thumb-wrap img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    opacity: 0;
    transition: opacity 0.2s;
  }
  /* 読めるまでは img を隠す → 壊れた画像アイコンを出さない */
  .thumb-wrap img.loaded {
    opacity: 1;
  }
  .thumb-loading {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: var(--surface-2);
  }
  .thumb-loading .shimmer {
    position: absolute;
    inset: 0;
    background: linear-gradient(
      100deg,
      transparent 30%,
      rgba(255, 255, 255, 0.06) 50%,
      transparent 70%
    );
    background-size: 200% 100%;
    animation: shimmer 1.3s ease-in-out infinite;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .thumb-loading .spinner {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 22px;
    height: 22px;
    margin: -11px 0 0 -11px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  .fav-btn {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.55);
    color: #c8c8c8;
    border: none;
    font-size: 17px;
    padding: 0;
    cursor: pointer;
    transition: transform 0.1s, background 0.15s, color 0.15s;
  }
  .fav-btn:hover {
    background: rgba(0, 0, 0, 0.85);
    color: #fff;
    transform: scale(1.12);
  }
  .fav-btn.on {
    color: var(--gold);
    background: rgba(0, 0, 0, 0.7);
  }
  .body { padding: 0.5rem 0.6rem; flex: 1; min-height: 0; }
  .title {
    font-size: 0.78rem;
    font-family: "SF Mono", Menlo, monospace;
    line-height: 1.3;
    word-break: break-all;
    max-height: 2.6em;
    overflow: hidden;
  }
  .meta {
    display: flex;
    gap: 0.4rem;
    margin-top: 0.35rem;
    font-size: 0.7rem;
    color: var(--muted);
    flex-wrap: wrap;
  }
  .chip {
    background: var(--surface-2);
    border: 1px solid var(--border);
    padding: 1px 6px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .chip.fmt { font-family: "SF Mono", Menlo, monospace; }
</style>
