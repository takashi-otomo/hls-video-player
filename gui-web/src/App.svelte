<script lang="ts">
  import Router from 'svelte-spa-router';
  import { onMount } from 'svelte';
  import Header from './lib/Header.svelte';
  import Library from './routes/Library.svelte';
  import Player from './routes/Player.svelte';
  import Settings from './routes/Settings.svelte';
  import TsManage from './routes/TsManage.svelte';
  import { api } from './lib/api';
  import { videos, favoriteIds, videosLoaded, settings } from './lib/stores';

  const routes = {
    '/': Library,
    '/player/:id': Player,
    '/settings': Settings,
    '/ts-manage': TsManage,
    '*': Library,
  };

  // 起動時に動画一覧 + お気に入りをプリロード (全ビュー共通)
  onMount(async () => {
    try {
      const [s] = await Promise.all([api.getSettings()]);
      settings.set(s);
    } catch (e) {
      console.warn('settings load failed', e);
    }
    try {
      const [vs, favs] = await Promise.all([api.videos(), api.favorites()]);
      videos.set(vs);
      favoriteIds.set(new Set(favs.favorites));
    } catch (e) {
      console.error('initial load failed', e);
    } finally {
      videosLoaded.set(true);
    }
  });
</script>

<Header />
<main>
  <Router {routes} />
</main>
