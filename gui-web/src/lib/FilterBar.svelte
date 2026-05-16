<script lang="ts">
  import { filterText, favoriteOnly, filteredVideos, thumbProgress } from './stores';

  $: p = $thumbProgress;
  $: pct = p.total > 0 ? Math.round((p.loaded / p.total) * 100) : 0;
  $: loadingTip =
    p.loading > 0
      ? '読込中:\n' +
        p.loadingTitles.join('\n') +
        (p.loading > p.loadingTitles.length
          ? `\n…他 ${p.loading - p.loadingTitles.length} 件`
          : '')
      : '';
</script>

<div class="filter-bar">
  <label class="fav-toggle">
    <input type="checkbox" bind:checked={$favoriteOnly} />
    ★ お気に入りのみ
  </label>
  <input
    type="search"
    placeholder="絞り込み (ファイル名 / ID)…"
    bind:value={$filterText}
  />

  <div class="progress" title={loadingTip}>
    <div class="bar" aria-label="サムネ読み込み進捗">
      <div class="fill" style="width:{pct}%"></div>
    </div>
    <span class="ptext">
      サムネ {p.loaded}/{p.total}
      {#if p.loading > 0}
        <span class="spin">⟳</span> {p.loading} 読込中
      {:else if p.loaded < p.total}
        <span class="muted">(スクロールで続き読込)</span>
      {:else if p.total > 0}
        <span class="ok">✓ 完了</span>
      {/if}
    </span>
  </div>

  <span class="count">{$filteredVideos.length} 件</span>
</div>

<style>
  .filter-bar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  .fav-toggle {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    cursor: pointer;
    white-space: nowrap;
  }
  input[type="search"] { flex: 1; max-width: 480px; }
  .progress {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-left: auto;
    cursor: default;
  }
  .bar {
    width: 120px;
    height: 6px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: var(--accent);
    transition: width 0.25s ease;
  }
  .ptext {
    font-size: 0.78rem;
    color: var(--muted);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .ptext .muted { opacity: 0.7; }
  .ptext .ok { color: var(--accent); }
  .spin {
    display: inline-block;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  .count { color: var(--muted); font-size: 0.85rem; white-space: nowrap; }
</style>
