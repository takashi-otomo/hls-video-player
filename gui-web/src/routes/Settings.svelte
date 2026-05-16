<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import { settings, videos, favoriteIds, videosLoaded } from '../lib/stores';

  let path = '';
  let message = '';
  let messageType: 'ok' | 'error' | '' = '';
  let saving = false;

  onMount(async () => {
    try {
      const s = await api.getSettings();
      settings.set(s);
      path = s.library_root;
    } catch (e: any) {
      message = `設定取得失敗: ${e.message}`;
      messageType = 'error';
    }
  });

  async function save() {
    saving = true;
    message = '';
    try {
      const r = await api.setLibraryRoot(path.trim());
      message = `✅ 保存しました: ${r.library_root}`;
      messageType = 'ok';
      settings.set({ library_root: r.library_root, exists: true });
      // 一覧を再ロード
      videosLoaded.set(false);
      const [vs, favs] = await Promise.all([api.videos(), api.favorites()]);
      videos.set(vs);
      favoriteIds.set(new Set(favs.favorites));
      videosLoaded.set(true);
      message += ` (${vs.length} 件検出)`;
    } catch (e: any) {
      message = `❌ ${e.message}`;
      messageType = 'error';
    } finally {
      saving = false;
    }
  }
</script>

<div class="settings">
  <h2>ライブラリパス設定</h2>
  <p class="hint">
    動画ファイルを置いてあるフォルダの絶対パスを指定します。<br />
    Docker コンテナ内のパス (例: <code>/library</code>) を指定してください。
  </p>
  <div class="row">
    <input
      type="text"
      bind:value={path}
      placeholder="/library"
      on:keydown={(e) => e.key === 'Enter' && save()}
    />
    <button on:click={save} disabled={saving}>
      {saving ? '保存中…' : '保存して反映'}
    </button>
  </div>
  {#if message}
    <p class={messageType}>{message}</p>
  {/if}
</div>

<style>
  .settings { padding: 2rem; max-width: 720px; }
  h2 { margin-top: 0; }
  .hint { color: var(--muted); font-size: 0.9rem; line-height: 1.6; }
  code {
    background: var(--surface-2);
    padding: 1px 5px;
    border-radius: 3px;
  }
  .row { display: flex; gap: 0.5rem; margin: 1rem 0; }
  .row input { flex: 1; }
  .ok { color: #7fd498; }
  .error { color: var(--danger); }
</style>
