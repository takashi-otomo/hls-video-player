<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import type { Video } from './types';

  export let video: Video;

  let mount: HTMLDivElement;
  let player: any = null;
  let videojs: any = null;

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
  });

  onDestroy(() => {
    disposed = true;
    if (player) {
      try {
        player.dispose();
      } catch {
        /* already disposed */
      }
    }
  });
</script>

<div class="hls-mount" bind:this={mount}></div>

<style>
  .hls-mount { width: 100%; max-width: 1280px; margin: 0 auto; }
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
