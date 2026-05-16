<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import type { TsStatus } from '../lib/types';
  import EntryTable from '../lib/EntryTable.svelte';
  import AddUrlForm from '../lib/AddUrlForm.svelte';
  import ConvertPanel from '../lib/ConvertPanel.svelte';

  let data: TsStatus | null = null;
  let loading = true;
  let error = '';

  async function load() {
    loading = true;
    error = '';
    try {
      data = await api.tsStatus();
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<div class="ts-manage">
  {#if loading}
    <div class="loading"><div class="spinner"></div>スキャン中…</div>
  {:else if error}
    <div class="error">エラー: {error}</div>
  {:else if data}
    <div class="summary">
      <strong>全 {data.entries.length} 件</strong>
      | MP4済: {data.counts.mp4}
      / MP4済(TS有): {data.counts.mp4_ts}
      / TS済: {data.counts.ts}
      / 未結合: {data.counts.pending}
      / 不完全: {data.counts.incomplete}
      / 未DL: {data.counts.no_dl}
      <button class="rescan" on:click={load}>↻ 再スキャン</button>
    </div>
    <EntryTable entries={data.entries} on:changed={load} />
    <AddUrlForm on:changed={load} />
    <ConvertPanel />
  {/if}
</div>

<style>
  .ts-manage { display: flex; flex-direction: column; }
  .summary {
    padding: 0.6rem 1rem;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .rescan { margin-left: auto; }
</style>
