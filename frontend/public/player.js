(async function () {
  const params = new URLSearchParams(window.location.search);
  const videoId = params.get('id');
  const titleEl = document.getElementById('video-title');
  const metaSource = document.getElementById('meta-source');
  const metaResolution = document.getElementById('meta-resolution');
  const metaBandwidth = document.getElementById('meta-bandwidth');
  const metaSprite = document.getElementById('meta-sprite');

  if (!videoId) {
    titleEl.textContent = '動画IDが指定されていません';
    return;
  }

  let video;
  try {
    const res = await fetch(`/api/videos/${encodeURIComponent(videoId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    video = await res.json();
  } catch (err) {
    titleEl.textContent = `読み込み失敗: ${err.message}`;
    return;
  }

  titleEl.textContent = video.title || video.id;
  metaSource.textContent = video.masterUrl;

  const playerEl = document.getElementById('streaming-player');
  const sourceEl = document.createElement('source');
  sourceEl.src = video.masterUrl;
  sourceEl.type = 'application/x-mpegURL';
  playerEl.appendChild(sourceEl);

  const player = videojs('streaming-player', {
    playbackRates: [0.5, 1, 1.25, 1.5, 2],
    fluid: true,
    html5: {
      vhs: {
        overrideNative: true,
        enableLowInitialPlaylist: true,
      },
    },
  });

  player.on('loadedmetadata', () => {
    try {
      const tech = player.tech({ IWillNotUseThisInPlugins: true });
      const vhs = tech && tech.vhs;
      if (!vhs) return;
      const rep = vhs.representations && vhs.representations();
      if (rep && rep.length) {
        metaResolution.textContent = rep.map((r) => `${r.width}x${r.height}`).join(', ');
      }
    } catch (_) { /* ignore */ }
  });

  player.on('bandwidthupdate', () => {
    try {
      const tech = player.tech({ IWillNotUseThisInPlugins: true });
      const vhs = tech && tech.vhs;
      if (vhs && vhs.stats) {
        const bps = vhs.stats.bandwidth || 0;
        metaBandwidth.textContent = `${(bps / 1000).toFixed(0)} kbps`;
      }
    } catch (_) { /* ignore */ }
  });

  if (video.sprite && typeof player.spriteThumbnails === 'function') {
    player.spriteThumbnails({
      url: video.sprite.url,
      width: video.sprite.tileWidth,
      height: video.sprite.tileHeight,
      columns: video.sprite.columns,
      interval: video.sprite.interval,
      responsive: 600,
      downlink: 1.5,
    });
    metaSprite.textContent = `${video.sprite.tileWidth}×${video.sprite.tileHeight}, ${video.sprite.interval}s間隔`;
  } else {
    metaSprite.textContent = video.sprite ? 'プラグイン未ロード' : 'スプライト未生成';
  }

  player.options({ disableSeekWhileScrubbingOnMobile: true });

  player.on('error', () => {
    console.error('playback error', player.error());
  });
})();
