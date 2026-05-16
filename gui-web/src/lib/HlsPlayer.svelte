<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import type { Video } from './types';
  import { warm, release, isAvailable, warmTick } from './warmer';

  export let video: Video;

  let mount: HTMLDivElement;
  let player: any = null;
  let videojs: any = null;

  // 強制ローディング UI: 実際に再生可能になる (loadedmetadata/playing)
  // まで必ずローディングを表示。HLS が 404 (ミラー未到達/Drive EDEADLK)
  // でも黒画面・エラーにせずローディング表示。
  // リトライ自体はグローバル warmer に委譲する (同時実行を一元管理)。
  let phase: 'loading' | 'ready' = 'loading';
  let attempt = 0;
  let reloadAt = 0;

  function hidePoster(e: Event) {
    const el = e.currentTarget as HTMLImageElement | null;
    if (el) el.style.display = 'none';
  }

  function markReady() {
    phase = 'ready';
    release(video.masterUrl); // 再生開始したら warmer から解放
  }
  function reloadSource() {
    if (!player || disposed || phase === 'ready') return;
    // 連続再 load を抑止 (warmer の通知が来てもクールダウン)
    const now = Date.now();
    if (now - reloadAt < 5000) return;
    reloadAt = now;
    attempt += 1;
    try {
      // query は再試行回数のみ変える。サーバのパス解決/キャッシュ鍵は
      // pathname 基準なので不変。ミラーに届いていれば今度は 200。
      player.src({
        src: `${video.masterUrl}?retry=${attempt}`,
        type: 'application/x-mpegURL',
      });
      player.load?.();
    } catch {
      /* dispose 済み等 */
    }
  }
  // warmer が masterUrl を取得できたら (= ミラー到達/キャッシュ済) 再 load。
  // ページ遷移しても warmer 側は別途サーバを温め続ける。
  $: if ($warmTick >= 0 && phase !== 'ready' && isAvailable(video.masterUrl)) {
    reloadSource();
  }

  function clamp(v: number, lo: number, hi: number) {
    return Math.max(lo, Math.min(hi, v));
  }
  function fmtTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
  }

  // playerFactory.js の attachSeekbarPreview を移植
  function attachSeekbarPreview(p: any, v: Video) {
    const thumbs = v.thumbs;
    if (!thumbs?.length) return;
    const tooltip = document.createElement('div');
    tooltip.style.cssText = `
      position:absolute;pointer-events:none;bottom:34px;width:160px;height:90px;
      background:#000 center/cover no-repeat;border:2px solid rgba(255,255,255,.85);
      border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.5);
      transform:translateX(-50%);display:none;z-index:2;`;
    const timeLabel = document.createElement('div');
    timeLabel.style.cssText = `
      position:absolute;left:50%;bottom:-22px;transform:translateX(-50%);
      padding:2px 6px;font-size:11px;font-weight:600;color:#fff;
      background:rgba(0,0,0,.75);border-radius:3px;white-space:nowrap;`;
    tooltip.appendChild(timeLabel);
    thumbs.forEach((t) => {
      const i = new Image();
      i.src = t.url;
    });
    let currentUrl = '';
    p.ready(() => {
      const pc = p.controlBar.progressControl.el();
      pc.style.position = 'relative';
      pc.appendChild(tooltip);
      const onMove = (evt: any) => {
        const dur = p.duration() || v.duration || 0;
        if (!dur || !isFinite(dur)) return;
        const rect = pc.getBoundingClientRect();
        if (rect.width === 0) return;
        const ratio = clamp((evt.clientX - rect.left) / rect.width, 0, 1);
        const pct = ratio * 100;
        let best = thumbs[0];
        let bestDiff = Infinity;
        for (const t of thumbs) {
          const d = Math.abs(t.percent - pct);
          if (d < bestDiff) {
            bestDiff = d;
            best = t;
          }
        }
        if (best.url !== currentUrl) {
          tooltip.style.backgroundImage = `url("${best.url}")`;
          currentUrl = best.url;
        }
        tooltip.style.display = 'block';
        tooltip.style.left = `${ratio * rect.width}px`;
        timeLabel.textContent = fmtTime(ratio * dur);
      };
      pc.addEventListener('mousemove', onMove);
      pc.addEventListener('mouseenter', () => (tooltip.style.display = 'block'));
      pc.addEventListener('mouseleave', () => (tooltip.style.display = 'none'));
    });
  }

  function attachQualitySelector(p: any) {
    const wrap = document.createElement('div');
    wrap.className = 'vjs-quality-wrap';
    wrap.innerHTML = `
      <button type="button" class="vjs-quality-toggle">
        <span class="vjs-quality-current">Auto</span></button>
      <ul class="vjs-quality-menu" role="listbox" hidden></ul>`;
    p.el().appendChild(wrap);
    const toggle = wrap.querySelector('.vjs-quality-toggle') as HTMLElement;
    const currentLabel = wrap.querySelector('.vjs-quality-current') as HTMLElement;
    const menu = wrap.querySelector('.vjs-quality-menu') as HTMLElement;
    let built = false;
    const getReps = () => {
      try {
        const tech = p.tech({ IWillNotUseThisInPlugins: true });
        return tech?.vhs?.representations ? tech.vhs.representations() : null;
      } catch {
        return null;
      }
    };
    const build = () => {
      if (built) return true;
      const reps = getReps();
      if (!reps || reps.length === 0) return false;
      const sorted = [...reps].sort(
        (a: any, b: any) => (b.height || 0) - (a.height || 0),
      );
      const items = [{ label: 'Auto', idx: -1 }].concat(
        sorted.map((r: any) => ({
          label: `${r.height}p`,
          idx: reps.indexOf(r),
        })),
      );
      menu.innerHTML = items
        .map(
          (it, i) =>
            `<li role="option" data-idx="${it.idx}" ${
              i === 0 ? 'aria-selected="true"' : ''
            }>${it.label}</li>`,
        )
        .join('');
      menu.addEventListener('click', (e: any) => {
        const li = e.target.closest('li');
        if (!li) return;
        const idx = parseInt(li.dataset.idx, 10);
        if (idx === -1) reps.forEach((r: any) => r.enabled(true));
        else reps.forEach((r: any, i: number) => r.enabled(i === idx));
        currentLabel.textContent = li.textContent;
        menu.hidden = true;
      });
      built = true;
      return true;
    };
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!build()) return;
      menu.hidden = !menu.hidden;
    });
    p.one('loadedmetadata', () => build());
    const close = (e: any) => {
      if (!wrap.contains(e.target)) menu.hidden = true;
    };
    document.addEventListener('click', close, { passive: true });
    p.one('dispose', () => document.removeEventListener('click', close));
  }

  let disposed = false;

  onMount(async () => {
    // video.js は重い (~700KB) ので player ページ表示時に動的 import。
    // これでライブラリ一覧の初期バンドルから切り離される。
    const mod = await import('video.js');
    // @ts-ignore CSS の動的 import
    await import('video.js/dist/video-js.css');
    if (disposed) return; // ロード中にページ離脱したら何もしない
    videojs = mod.default;

    const el = document.createElement('video-js');
    el.className = 'video-js vjs-default-skin vjs-big-play-centered';
    el.setAttribute('controls', '');
    el.setAttribute('preload', 'auto');
    if (video.posterUrl) el.setAttribute('poster', video.posterUrl);
    const source = document.createElement('source');
    source.src = video.masterUrl;
    source.type = 'application/x-mpegURL';
    el.appendChild(source);
    mount.appendChild(el);

    player = videojs(el, {
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      aspectRatio: '16:9',
      html5: { vhs: { overrideNative: true, enableLowInitialPlaylist: true } },
    });
    attachSeekbarPreview(player, video);
    attachQualitySelector(player);
    player.options({ disableSeekWhileScrubbingOnMobile: true });

    // 再生可能になったら強制ローディングを解除
    const onReady = () => markReady();
    player.on('loadedmetadata', onReady);
    player.on('loadeddata', onReady);
    player.on('canplay', onReady);
    player.on('playing', onReady);
    // 読み込み失敗 (HLS 404 等) は黒画面・エラー表示にせず、
    // グローバル warmer に登録して裏で取得を試行 (同時実行は一元管理)。
    player.on('error', () => {
      if (phase === 'ready') return;
      try {
        player.error(null);
      } catch {
        /* noop */
      }
      warm(video.masterUrl, 'manifest');
    });
    // 最初から warmer に積む (ミラー未到達でも遷移後まで温め続ける)
    warm(video.masterUrl, 'manifest');
  });

  onDestroy(() => {
    disposed = true;
    // player を離れたら manifest の温めは解放 (グリッドのサムネ温めを優先)
    release(video.masterUrl);
    if (player) {
      try {
        player.dispose();
      } catch {
        /* already disposed */
      }
    }
  });
</script>

<div class="hls-stage">
  <div class="hls-mount" bind:this={mount}></div>
  {#if phase !== 'ready'}
    <div class="player-loading" role="status" aria-live="polite">
      {#if video.posterUrl}
        <img
          class="pl-poster"
          src={video.posterUrl}
          alt=""
          aria-hidden="true"
          on:error={hidePoster}
        />
      {/if}
      <div class="pl-center">
        <div class="pl-spinner"></div>
        <p class="pl-title">読み込み中…</p>
        <small class="pl-sub">
          {#if attempt > 0}
            ミラー未到達のため待機中・自動再試行 {attempt} 回目
          {:else}
            動画を準備しています
          {/if}
        </small>
      </div>
    </div>
  {/if}
</div>

<style>
  .hls-stage {
    position: relative;
    width: 100%;
    max-width: 1280px;
    margin: 0 auto;
    /* video.js ロード前でもローディングを正しく表示できるよう枠を確保 */
    aspect-ratio: 16 / 9;
  }
  .hls-mount { width: 100%; }
  .player-loading {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #000;
    overflow: hidden;
    z-index: 50;
  }
  /* 強制ローディング中は video.js のエラーモーダルを出さない
     (代わりにこのローディング UI を表示し自動リトライする) */
  :global(.hls-stage .vjs-error-display) {
    display: none !important;
  }
  :global(.hls-stage .video-js.vjs-error .vjs-loading-spinner) {
    display: none !important;
  }
  .player-loading .pl-poster {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0.25;
    filter: blur(8px);
  }
  .player-loading .pl-center {
    position: relative;
    text-align: center;
    color: #e8e8e8;
  }
  .player-loading .pl-spinner {
    width: 46px;
    height: 46px;
    margin: 0 auto 0.9rem;
    border: 3px solid rgba(255, 255, 255, 0.25);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: pl-spin 0.8s linear infinite;
  }
  @keyframes pl-spin {
    to { transform: rotate(360deg); }
  }
  .player-loading .pl-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
  }
  .player-loading .pl-sub {
    display: block;
    margin-top: 0.3rem;
    font-size: 0.8rem;
    color: #b8b8b8;
  }
  :global(.hls-mount .video-js) {
    width: 100% !important;
    height: auto !important;
    max-height: calc(100vh - 120px);
  }
  :global(.vjs-quality-wrap) {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 3;
  }
  :global(.vjs-quality-toggle) {
    background: rgba(0, 0, 0, 0.6);
    color: #fff;
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 12px;
    cursor: pointer;
  }
  :global(.vjs-quality-menu) {
    list-style: none;
    margin: 4px 0 0;
    padding: 4px 0;
    position: absolute;
    right: 0;
    background: rgba(0, 0, 0, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 4px;
    min-width: 80px;
  }
  :global(.vjs-quality-menu li) {
    padding: 4px 12px;
    color: #fff;
    font-size: 12px;
    cursor: pointer;
  }
  :global(.vjs-quality-menu li:hover) { background: rgba(255, 255, 255, 0.12); }
  :global(.vjs-quality-menu li[aria-selected='true']) { color: var(--accent); }
</style>
