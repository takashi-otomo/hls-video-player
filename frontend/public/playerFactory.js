// Video.js + VHS ストリーミングプレイヤーを任意のコンテナ要素に
// マウントする再利用可能ファクトリ。インライン展開と単独ページの両方で使用。
(function () {
  async function init(container, videoId) {
    const res = await fetch(`/api/videos/${encodeURIComponent(videoId)}`);
    if (!res.ok) throw new Error(`動画情報の取得に失敗: HTTP ${res.status}`);
    const video = await res.json();

    const el = document.createElement('video-js');
    el.className = 'video-js vjs-default-skin vjs-big-play-centered vjs-fluid';
    el.setAttribute('controls', '');
    el.setAttribute('preload', 'auto');
    const source = document.createElement('source');
    source.src = video.masterUrl;
    source.type = 'application/x-mpegURL';
    el.appendChild(source);

    container.innerHTML = '';
    container.appendChild(el);

    const player = videojs(el, {
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      fluid: true,
      html5: {
        vhs: { overrideNative: true, enableLowInitialPlaylist: true },
      },
    });

    if (video.sprite) attachSeekbarPreview(player, video.sprite);
    player.options({ disableSeekWhileScrubbingOnMobile: true });
    player.on('error', () => console.error('playback error', player.error()));

    return {
      video,
      player,
      dispose() {
        try { player.dispose(); } catch (_) { /* already disposed */ }
      },
    };
  }

  function attachSeekbarPreview(player, sprite) {
    const { url, tileWidth, tileHeight, columns, interval } = sprite;

    const tooltip = document.createElement('div');
    tooltip.className = 'vjs-seek-preview';
    tooltip.style.cssText = `
      position: absolute; pointer-events: none; bottom: 34px;
      width: ${tileWidth}px; height: ${tileHeight}px;
      background-image: url("${url}"); background-repeat: no-repeat;
      border: 2px solid rgba(255, 255, 255, 0.85); border-radius: 4px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
      transform: translateX(-50%); display: none; z-index: 2;
    `;

    const timeLabel = document.createElement('div');
    timeLabel.className = 'vjs-seek-preview-time';
    timeLabel.style.cssText = `
      position: absolute; left: 50%; bottom: -22px; transform: translateX(-50%);
      padding: 2px 6px; font-size: 11px; font-weight: 600; color: #fff;
      background: rgba(0, 0, 0, 0.75); border-radius: 3px; white-space: nowrap;
    `;
    tooltip.appendChild(timeLabel);

    const preloader = new Image();
    preloader.src = url;

    player.ready(() => {
      const progressControl = player.controlBar.progressControl.el();
      progressControl.style.position = 'relative';
      progressControl.appendChild(tooltip);

      progressControl.addEventListener('mousemove', onMove);
      progressControl.addEventListener('mouseenter', () => { tooltip.style.display = 'block'; });
      progressControl.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
      progressControl.addEventListener('touchmove', (e) => { if (e.touches[0]) onMove(e.touches[0]); }, { passive: true });
      progressControl.addEventListener('touchstart', () => { tooltip.style.display = 'block'; }, { passive: true });
      progressControl.addEventListener('touchend', () => { tooltip.style.display = 'none'; });
    });

    function onMove(evt) {
      const duration = player.duration();
      if (!duration || !isFinite(duration)) return;

      const progressControl = player.controlBar.progressControl.el();
      const rect = progressControl.getBoundingClientRect();
      if (rect.width === 0) return;
      const ratio = clamp((evt.clientX - rect.left) / rect.width, 0, 1);
      const time = ratio * duration;

      const index = Math.min(Math.floor(time / interval), Math.floor(duration / interval));
      const x = (index % columns) * tileWidth;
      const y = Math.floor(index / columns) * tileHeight;

      tooltip.style.display = 'block';
      tooltip.style.left = `${ratio * rect.width}px`;
      tooltip.style.backgroundPosition = `-${x}px -${y}px`;
      timeLabel.textContent = formatTime(time);
    }
  }

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
  }

  window.HlsPlayer = { init };
})();
