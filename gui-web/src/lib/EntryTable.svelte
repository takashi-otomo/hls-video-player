<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { TsEntry } from './types';
  import { formatSize } from './format';
  import { api } from './api';

  export let entries: TsEntry[] = [];

  const dispatch = createEventDispatcher();
  let checked = new Set<string>();
  let statusFilter = new Set<string>([
    'MP4済', 'MP4済(TS有)', 'TS済', '未結合', '不完全', '未DL',
  ]);

  $: visible = entries.filter((e) => statusFilter.has(e.status));

  function toggleCheck(uuid: string) {
    if (checked.has(uuid)) checked.delete(uuid);
    else checked.add(uuid);
    checked = new Set(checked);
  }
  function selectAll() {
    checked = new Set(visible.map((e) => e.uuid));
  }
  function deselectAll() {
    checked = new Set();
  }

  async function removeChecked() {
    const ids = [...checked].filter((id) =>
      entries.find((e) => e.uuid === id && e.url),
    );
    if (ids.length === 0) {
      alert('index に登録された行をチェックしてください');
      return;
    }
    if (!confirm(`${ids.length} 件を index.md から削除しますか？`)) return;
    await api.removeFromIndex(ids);
    checked = new Set();
    dispatch('changed');
  }

  async function deleteTsPartsChecked() {
    const ids = [...checked].filter((id) => {
      const e = entries.find((x) => x.uuid === id);
      return e && (e.has_mp4 || e.has_ts) && e.part_count > 0;
    });
    if (ids.length === 0) {
      alert('MP4化済みで TSパートが残っている行をチェックしてください');
      return;
    }
    if (
      !confirm(
        `${ids.length} 件の TSパートを削除しますか？\n` +
          'MP4 は残ります。この操作は元に戻せません。',
      )
    )
      return;
    let total = 0;
    for (const id of ids) {
      const r = await api.deleteTsParts(id);
      total += r.deleted;
    }
    alert(`${total} ファイル削除しました`);
    checked = new Set();
    dispatch('changed');
  }

  const STATUS_COLORS: Record<string, string> = {
    'MP4済': '#66bb6a',
    'MP4済(TS有)': '#f0c47a',
    'TS済': '#66bb6a',
    '未結合': '#e6e8eb',
    '不完全': '#ff9800',
    '未DL': '#e53935',
  };

  function play(e: TsEntry) {
    if (e.hls === 'done') {
      location.hash = `#/player/${encodeURIComponent(e.uuid)}`;
    } else {
      alert('まだ HLS 変換されていません');
    }
  }
</script>

<div class="toolbar">
  <button on:click={selectAll}>全選択</button>
  <button on:click={deselectAll}>全解除</button>
  <button on:click={removeChecked}>📝 index から削除</button>
  <button on:click={deleteTsPartsChecked}>🗑 TSパート削除</button>
  <span class="sep">|</span>
  {#each ['MP4済', 'MP4済(TS有)', 'TS済', '未結合', '不完全', '未DL'] as s}
    <label class="filter-chip">
      <input
        type="checkbox"
        checked={statusFilter.has(s)}
        on:change={() => {
          if (statusFilter.has(s)) statusFilter.delete(s);
          else statusFilter.add(s);
          statusFilter = new Set(statusFilter);
        }}
      />
      {s}
    </label>
  {/each}
  <span class="count">{visible.length} / {entries.length} 件</span>
</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th></th>
        <th>UUID</th>
        <th>状態</th>
        <th>HLS</th>
        <th>パート</th>
        <th>サイズ</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody>
      {#each visible as e (e.uuid)}
        <tr class:checked={checked.has(e.uuid)}>
          <td>
            <input
              type="checkbox"
              checked={checked.has(e.uuid)}
              on:change={() => toggleCheck(e.uuid)}
            />
          </td>
          <td class="uuid" title={e.uuid}>{e.uuid}</td>
          <td style="color:{STATUS_COLORS[e.status] ?? 'inherit'}">{e.status}</td>
          <td>{e.hls === 'done' ? '🎞 済' : '—'}</td>
          <td>{e.part_count > 0 ? `${e.part_count}` : '—'}</td>
          <td>{e.total_size > 0 ? formatSize(e.total_size) : '—'}</td>
          <td>
            {#if e.hls === 'done'}
              <button class="play" on:click={() => play(e)}>▶ 再生</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
  }
  .sep { color: var(--border); }
  .filter-chip {
    display: flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  .count { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
  .table-wrap { overflow: auto; max-height: calc(100vh - 320px); }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th, td {
    text-align: left;
    padding: 0.35rem 0.6rem;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  th { position: sticky; top: 0; background: var(--surface); }
  tr.checked { background: #1b3a1b; }
  .uuid {
    font-family: Menlo, monospace;
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .play { background: var(--accent-strong); color: #fff; border: none; padding: 0.2rem 0.6rem; }
</style>
