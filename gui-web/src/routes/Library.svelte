<script lang="ts">
  import { onMount } from 'svelte';
  import { filteredVideos, videosLoaded } from '../lib/stores';
  import { api } from '../lib/api';
  import VirtualGrid from '../lib/VirtualGrid.svelte';
  import Card from '../lib/Card.svelte';
  import FilterBar from '../lib/FilterBar.svelte';

  let showHelp = false;
  let readError: string | null = null;

  onMount(async () => {
    try {
      const h = await api.health();
      if (h.file_read && !h.file_read.ok) {
        readError = h.file_read.reason;
      }
    } catch {
      /* health 取得失敗は無視 */
    }
  });

  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    const inField = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
    if (e.key === '/' && !inField) {
      e.preventDefault();
      const el = document.querySelector<HTMLInputElement>(
        '.filter-bar input[type="search"]',
      );
      el?.focus();
    } else if (e.key === '?' && !inField) {
      showHelp = !showHelp;
    } else if (e.key === 'Escape') {
      showHelp = false;
    }
  }
</script>

<svelte:window on:keydown={onKey} />

{#if readError}
  <div class="read-error-banner">
    ⚠ ファイル本文の読み込みに失敗しています。サムネ・再生ができません。<br />
    <small>{readError}</small>
  </div>
{/if}

<FilterBar />

{#if showHelp}
  <!-- オーバーレイ自体をクリックで閉じる button にする (a11y) -->
  <button
    type="button"
    class="help-overlay"
    aria-label="ヘルプを閉じる"
    on:click={() => (showHelp = false)}
  ></button>
  <div class="help" role="dialog" aria-modal="true" aria-label="キーボードショートカット">
    <h3>キーボードショートカット</h3>
    <ul>
      <li><kbd>/</kbd> フィルタ欄にフォーカス</li>
      <li><kbd>?</kbd> このヘルプ</li>
      <li>プレイヤー: <kbd>←</kbd>/<kbd>→</kbd> 前後の動画</li>
      <li>プレイヤー: <kbd>F</kbd> お気に入り / <kbd>Esc</kbd> 閉じる</li>
    </ul>
    <button on:click={() => (showHelp = false)}>閉じる</button>
  </div>
{/if}

{#if !$videosLoaded}
  <div class="loading"><div class="spinner"></div>読み込み中…</div>
{:else if $filteredVideos.length === 0}
  <div class="empty">
    条件に一致する動画がありません。<br />
    変換は「TS結合管理」タブ、または CLI <code>hls-convert</code> で実行してください。
  </div>
{:else}
  <VirtualGrid
    items={$filteredVideos}
    itemWidth={240}
    itemHeight={210}
    gap={14}
    let:item
  >
    <Card video={item} />
  </VirtualGrid>
{/if}

<style>
  code {
    background: var(--surface-2);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.85em;
  }
  .help-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    border: none;
    padding: 0;
    margin: 0;
    cursor: default;
    z-index: 100;
  }
  .help {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem 2rem;
    max-width: 420px;
    z-index: 101;
  }
  .help h3 { margin-top: 0; }
  .help ul { line-height: 2; padding-left: 1.2rem; }
  kbd {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 6px;
    font-family: Menlo, monospace;
    font-size: 0.85em;
  }
  .read-error-banner {
    background: #3a1f1f;
    color: #ffb3b3;
    border-bottom: 1px solid #6a2c2c;
    padding: 0.6rem 1rem;
    font-size: 0.9rem;
    line-height: 1.5;
  }
  .read-error-banner small { color: #d99; }
</style>
