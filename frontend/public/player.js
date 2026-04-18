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

  if (video.sprite) {
    attachSeekbarPreview(player, video.sprite);
    metaSprite.textContent = `${video.sprite.tileWidth}×${video.sprite.tileHeight}, ${video.sprite.interval}s間隔`;
  } else {
    metaSprite.textContent = 'スプライト未生成';
  }

  player.options({ disableSeekWhileScrubbingOnMobile: true });

  player.on('error', () => {
    console.error('playback error', player.error());
  });
})();

// 独自実装のシークバーサムネイルプレビュー
// - サーバーで生成した 10×N タイルのスプライト画像を使用
// - シークバー上のホバー位置を秒に換算 → タイルインデックス i を計算
// - background-position で該当タイルを表示
function attachSeekbarPreview(player, sprite) {
  const { url, tileWidth, tileHeight, columns, interval } = sprite;

  const tooltip = document.createElement('div');
  tooltip.className = 'vjs-seek-preview';
  tooltip.style.cssText = `
    position: absolute;
    pointer-events: none;
    bottom: 34px;
    width: ${tileWidth}px;
    height: ${tileHeight}px;
    background-image: url("${url}");
    background-repeat: no-repeat;
    border: 2px solid rgba(255, 255, 255, 0.85);
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    transform: translateX(-50%);
    display: none;
    z-index: 2;
  `;

  const timeLabel = document.createElement('div');
  timeLabel.className = 'vjs-seek-preview-time';
  timeLabel.style.cssText = `
    position: absolute;
    left: 50%;
    bottom: -22px;
    transform: translateX(-50%);
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
    color: #fff;
    background: rgba(0, 0, 0, 0.75);
    border-radius: 3px;
    white-space: nowrap;
  `;
  tooltip.appendChild(timeLabel);

  // プリロードして最初のホバーで即表示できるようにする
  const preloader = new Image();
  preloader.src = url;

  player.ready(() => {
    const progressControl = player.controlBar.progressControl.el();
    progressControl.style.position = 'relative';
    progressControl.appendChild(tooltip);

    progressControl.addEventListener('mousemove', onMove);
    progressControl.addEventListener('mouseenter', () => { tooltip.style.display = 'block'; });
    progressControl.addEventListener('mouseleave', () => { tooltip.style.display = 'none'; });
    progressControl.addEventListener('touchmove', (e) => {
      if (e.touches[0]) onMove(e.touches[0]);
    }, { passive: true });
    progressControl.addEventListener('touchstart', () => { tooltip.style.display = 'block'; }, { passive: true });
    progressControl.addEventListener('touchend', () => { tooltip.style.display = 'none'; });
  });

  function onMove(evt) {
    const duration = player.duration();
    if (!duration || !isFinite(duration)) return;

    const progressControl = player.controlBar.progressControl.el();
    const rect = progressControl.getBoundingClientRect();
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
