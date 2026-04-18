(async function () {
  const listEl = document.getElementById('video-list');
  const statusEl = document.getElementById('library-status');

  try {
    const res = await fetch('/api/videos');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const videos = await res.json();

    if (videos.length === 0) {
      statusEl.textContent = 'まだ動画がありません。下の手順に従って追加してください。';
      return;
    }

    statusEl.remove();
    for (const v of videos) {
      const li = document.createElement('li');
      li.className = 'video-card';
      const hasSprite = v.sprite ? '✅ プレビュー付き' : '— プレビューなし';
      li.innerHTML = `
        <a href="/player.html?id=${encodeURIComponent(v.id)}">
          <h3>${escapeHtml(v.title)}</h3>
          <p class="video-card__meta">id: <code>${escapeHtml(v.id)}</code></p>
          <p class="video-card__meta">${hasSprite}</p>
        </a>
      `;
      listEl.appendChild(li);
    }
  } catch (err) {
    statusEl.textContent = `ライブラリの取得に失敗しました: ${err.message}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
})();
