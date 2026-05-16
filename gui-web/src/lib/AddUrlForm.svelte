<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { api } from './api';

  const dispatch = createEventDispatcher();
  let text = '';
  let message = '';
  let messageType: 'ok' | 'error' | '' = '';

  async function add() {
    const urls = text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      message = 'URL を貼り付けてください';
      messageType = 'error';
      return;
    }
    try {
      const r = await api.addToIndex(urls);
      const parts: string[] = [];
      if (r.added) parts.push(`${r.added} 件追加`);
      if (r.skipped) parts.push(`${r.skipped} 件重複`);
      if (r.invalid) parts.push(`${r.invalid} 件無効`);
      message = `✅ ${parts.join('、')}`;
      messageType = 'ok';
      if (r.added > 0) {
        text = '';
        dispatch('changed');
      }
    } catch (e: any) {
      message = `❌ ${e.message}`;
      messageType = 'error';
    }
  }
</script>

<div class="add-form">
  <label for="add-url-textarea">index.md に URL を追加 (1 行 1 URL)</label>
  <textarea
    id="add-url-textarea"
    bind:value={text}
    rows="3"
    placeholder="https://example.com/posts/..."
  ></textarea>
  <div class="row">
    {#if message}<span class={messageType}>{message}</span>{/if}
    <button on:click={add}>追加</button>
  </div>
</div>

<style>
  .add-form { padding: 0.75rem 1rem; border-top: 1px solid var(--border); }
  label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 4px; }
  textarea {
    width: 100%;
    background: var(--surface-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px 8px;
    font-family: Menlo, monospace;
    font-size: 12px;
    resize: vertical;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 6px;
    justify-content: flex-end;
  }
  .ok { color: #7fd498; font-size: 0.85rem; margin-right: auto; }
  .error { color: var(--danger); font-size: 0.85rem; margin-right: auto; }
</style>
