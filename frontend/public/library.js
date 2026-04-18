(function () {
  const sourcesStatus = document.getElementById('sources-status');
  const sourcesTable = document.getElementById('sources-table');
  const sourcesBody = sourcesTable.querySelector('tbody');
  const refreshBtn = document.getElementById('refresh-sources');

  // videoId → setInterval handle（ジョブポーリング用）
  const jobPollers = new Map();

  refreshBtn.addEventListener('click', loadSources);

  loadSources();

  async function loadSources() {
    try {
      const res = await fetch('/api/sources');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sources = await res.json();
      renderSources(sources);
    } catch (err) {
      sourcesStatus.textContent = `一覧の取得に失敗: ${err.message}`;
      sourcesStatus.hidden = false;
      sourcesTable.hidden = true;
    }
  }

  function renderSources(sources) {
    if (sources.length === 0) {
      sourcesStatus.textContent = 'media/source/ にファイルがありません。MP4 などを置いて「更新」を押してください。';
      sourcesStatus.hidden = false;
      sourcesTable.hidden = true;
      return;
    }
    sourcesStatus.hidden = true;
    sourcesTable.hidden = false;

    sourcesBody.innerHTML = '';
    for (const s of sources) {
      const tr = document.createElement('tr');
      tr.dataset.videoId = s.videoId;
      tr.innerHTML = `
        <td><code>${escapeHtml(s.filename)}</code></td>
        <td class="num">${formatBytes(s.sizeBytes)}</td>
        <td>${formatDate(s.modifiedAt)}</td>
        <td class="status-cell"></td>
        <td class="action-cell"></td>
      `;
      sourcesBody.appendChild(tr);
      applyRowState(tr, s);

      // アクティブジョブが残っていれば再開（ページ再読み込み対応）
      if (s.activeJobId) pollJob(s.activeJobId, s.videoId);
    }
  }

  function applyRowState(tr, source) {
    const statusCell = tr.querySelector('.status-cell');
    const actionCell = tr.querySelector('.action-cell');
    statusCell.innerHTML = '';
    actionCell.innerHTML = '';

    if (source.activeJobId) {
      statusCell.appendChild(badge('🔄 変換中…', 'running'));
      const btn = document.createElement('button');
      btn.className = 'btn btn-secondary';
      btn.textContent = '処理中';
      btn.disabled = true;
      actionCell.appendChild(btn);
      return;
    }

    if (source.converted) {
      statusCell.appendChild(badge('✓ 変換済', 'ok'));
      const link = document.createElement('a');
      link.className = 'btn btn-primary';
      link.href = `/player.html?id=${encodeURIComponent(source.videoId)}`;
      link.textContent = '▶ 再生';
      actionCell.appendChild(link);
      return;
    }

    statusCell.appendChild(badge('未変換', 'pending'));
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary';
    btn.textContent = '変換';
    btn.addEventListener('click', () => triggerConvert(source.filename, source.videoId, tr));
    actionCell.appendChild(btn);
  }

  async function triggerConvert(filename, videoId, tr) {
    const actionCell = tr.querySelector('.action-cell');
    const statusCell = tr.querySelector('.status-cell');
    actionCell.innerHTML = '';
    statusCell.innerHTML = '';
    statusCell.appendChild(badge('🚀 開始中…', 'running'));

    try {
      const res = await fetch(`/api/sources/${encodeURIComponent(filename)}/convert`, { method: 'POST' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);

      statusCell.innerHTML = '';
      statusCell.appendChild(badge('🔄 変換中…', 'running'));
      pollJob(body.jobId, videoId);
    } catch (err) {
      statusCell.innerHTML = '';
      statusCell.appendChild(badge(`失敗: ${err.message}`, 'error'));
      const retry = document.createElement('button');
      retry.className = 'btn btn-primary';
      retry.textContent = '再試行';
      retry.addEventListener('click', () => triggerConvert(filename, videoId, tr));
      actionCell.appendChild(retry);
    }
  }

  function pollJob(jobId, videoId) {
    if (jobPollers.has(videoId)) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const job = await res.json();

        const tr = document.querySelector(`tr[data-video-id="${cssEscape(videoId)}"]`);
        if (tr) updateTrFromJob(tr, job);

        if (job.state === 'completed' || job.state === 'failed') {
          clearInterval(interval);
          jobPollers.delete(videoId);
          await loadSources();
        }
      } catch (err) {
        clearInterval(interval);
        jobPollers.delete(videoId);
      }
    }, 2000);

    jobPollers.set(videoId, interval);
  }

  function updateTrFromJob(tr, job) {
    const statusCell = tr.querySelector('.status-cell');
    statusCell.innerHTML = '';
    if (job.state === 'pending') statusCell.appendChild(badge('待機中', 'running'));
    else if (job.state === 'running') {
      const stage = job.stage === 'sprite' ? 'サムネイル生成中' : 'HLS変換中';
      statusCell.appendChild(badge(`🔄 ${stage}`, 'running'));
    } else if (job.state === 'completed') {
      statusCell.appendChild(badge('✓ 変換済', 'ok'));
    } else if (job.state === 'failed') {
      statusCell.appendChild(badge(`✗ 失敗: ${job.error || ''}`.slice(0, 80), 'error'));
    }
  }

  function badge(text, variant) {
    const span = document.createElement('span');
    span.className = `badge badge-${variant}`;
    span.textContent = text;
    return span;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function cssEscape(s) {
    return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/"/g, '\\"');
  }

  function formatBytes(n) {
    if (n < 1024) return `${n} B`;
    const units = ['KB', 'MB', 'GB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`;
  }

  function formatDate(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
})();
