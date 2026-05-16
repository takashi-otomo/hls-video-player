<script lang="ts">
  import { location } from 'svelte-spa-router';
  import { settings } from './stores';
</script>

<header>
  <h1>🎞 HLS Video Library</h1>
  <nav>
    <a href="#/" class:active={$location === '/'}>ライブラリ</a>
    <a href="#/ts-manage" class:active={$location === '/ts-manage'}>TS結合管理</a>
    <a href="#/settings" class:active={$location === '/settings'}>設定</a>
  </nav>
  {#if $settings}
    <span class="lib-path" title={$settings.library_root}>
      {$settings.library_root}
    </span>
  {/if}
</header>

<style>
  header {
    display: flex;
    align-items: center;
    gap: 1.2rem;
    padding: 0.5rem 1rem;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  h1 { margin: 0; font-size: 1rem; font-weight: 600; white-space: nowrap; }
  nav { display: flex; gap: 0.5rem; }
  nav a {
    padding: 0.3rem 0.7rem;
    border-radius: 4px;
    color: var(--muted);
    font-size: 0.9rem;
  }
  nav a:hover { color: var(--text); }
  nav a.active { background: var(--accent); color: #04121f; }
  .lib-path {
    margin-left: auto;
    font-size: 0.75rem;
    color: var(--muted);
    font-family: "SF Mono", Menlo, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 40vw;
  }
</style>
