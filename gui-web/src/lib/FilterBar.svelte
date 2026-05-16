<script lang="ts">
  import { filterText, favoriteOnly, filteredVideos } from './stores';
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
  .count { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
</style>
