(function () {
  const sourcesStatus = document.getElementById('sources-status');
  const sourcesContainer = document.getElementById('sources-container');
  const refreshBtn = document.getElementById('refresh-sources');
  const viewToggle = document.querySelector('.view-toggle');

  // videoId → setInterval handle（ジョブポーリング用）
  const jobPollers = new Map();

  // 表示モード: 'card' | 'list'（ユーザー選択を localStorage に保存）
  const VIEW_STORAGE_KEY = 'hls-player.viewMode';
  let viewMode = localStorage.getItem(VIEW_STORAGE_KEY) || 'card';
  applyViewToggleUi();

  // 現在インライン展開中のプレイヤー情報（1件のみ）
  // { videoId, triggerEl, expansionEl, instance, onRowRef: 'row' | 'card' }
  let expanded = null;

  refreshBtn.addEventListener('click', loadSources);
  viewToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.view-btn');
    if (!btn) return;
    const next = btn.dataset.view;
    if (!next || next === viewMode) return;
    viewMode = next;
    localStorage.setItem(VIEW_STORAGE_KEY, viewMode);
    applyViewToggleUi();
    loadSources();
  });

  loadSources();

  function applyViewToggleUi() {
    viewToggle.querySelectorAll('.view-btn').forEach((b) =>
      b.setAttribute('aria-pressed', String(b.dataset.view === viewMode))
    );
  }

  async function loadSources() {
    try {
      const res = await fetch('/api/sources');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const sources = await res.json();
      renderSources(sources);
    } catch (err) {
      sourcesStatus.textContent = `一覧の取得に失敗: ${err.message}`;
      sourcesStatus.hidden = false;
      sourcesContainer.innerHTML = '';
    }
  }

  function renderSources(sources) {
    collapseExpanded();
    sourcesContainer.innerHTML = '';

    if (sources.length === 0) {
      sourcesStatus.textContent = 'media/source/ にファイルがありません。MP4 などを置いて「更新」を押してください。';
      sourcesStatus.hidden = false;
      return;
    }
    sourcesStatus.hidden = true;

    if (viewMode === 'card') renderCards(sources);
    else renderList(sources);

    // ページ再描画時に既存ジョブがあればポーリング再開
    for (const s of sources) {
      if (s.activeJobId) pollJob(s.activeJobId, s.videoId);
    }
  }

  // ===== List view (table) =====

  function renderList(sources) {
    const table = document.createElement('table');
    table.className = 'sources-table';
    table.innerHTML = `
      <thead><tr>
        <th>ファイル名</th>
        <th class="num">サイズ</th>
        <th>更新日時</th>
        <th>状態</th>
        <th>操作</th>
      </tr></thead><tbody></tbody>
    `;
    const tbody = table.querySelector('tbody');
    for (const s of sources) {
      const tr = document.createElement('tr');
      tr.dataset.videoId = s.videoId;
      tr.dataset.role = 'row';
      tr.innerHTML = `
        <td><code>${escapeHtml(s.filename)}</code></td>
        <td class="num">${formatBytes(s.sizeBytes)}</td>
        <td>${formatDate(s.modifiedAt)}</td>
        <td class="status-cell"></td>
        <td class="action-cell"></td>
      `;
      tbody.appendChild(tr);
      applyRowState(tr, s);
    }
    sourcesContainer.appendChild(table);
  }

  function applyRowState(tr, source) {
    const statusCell = tr.querySelector('.status-cell');
    const actionCell = tr.querySelector('.action-cell');
    statusCell.innerHTML = '';
    actionCell.innerHTML = '';

    if (source.activeJobId) {
      statusCell.appendChild(badge('🔄 変換中…', 'running'));
      actionCell.appendChild(disabledBtn('処理中'));
      return;
    }
    if (source.converted) {
      statusCell.appendChild(badge('✓ 変換済', 'ok'));
      actionCell.appendChild(playButton(source, tr));
      return;
    }
    statusCell.appendChild(badge('未変換', 'pending'));
    actionCell.appendChild(convertButton(source, tr));
  }

  // ===== Card view (grid) =====

  function renderCards(sources) {
    const grid = document.createElement('div');
    grid.className = 'video-grid';
    for (const s of sources) {
      const card = document.createElement('article');
      card.className = 'video-card';
      card.dataset.videoId = s.videoId;
      card.dataset.role = 'card';

      const thumb = buildThumb(s);
      const body = document.createElement('div');
      body.className = 'video-card__body';
      body.innerHTML = `
        <h3 class="video-card__title">${escapeHtml(s.filename)}</h3>
        <p class="video-card__meta">${formatBytes(s.sizeBytes)} · ${formatDate(s.modifiedAt)}</p>
        <div class="video-card__actions">
          <div class="status-cell"></div>
          <div class="action-cell"></div>
        </div>
      `;
      card.appendChild(thumb);
      card.appendChild(body);
      grid.appendChild(card);
      applyCardState(card, s);
    }
    sourcesContainer.appendChild(grid);
  }

  function applyCardState(card, source) {
    const statusCell = card.querySelector('.status-cell');
    const actionCell = card.querySelector('.action-cell');
    statusCell.innerHTML = '';
    actionCell.innerHTML = '';

    if (source.activeJobId) {
      statusCell.appendChild(badge('🔄 変換中…', 'running'));
      actionCell.appendChild(disabledBtn('処理中'));
      return;
    }
    if (source.converted) {
      statusCell.appendChild(badge('✓ 変換済', 'ok'));
      actionCell.appendChild(playButton(source, card));
      return;
    }
    statusCell.appendChild(badge('未変換', 'pending'));
    actionCell.appendChild(convertButton(source, card));
  }

  // 先頭サムネイルを生成（スプライト1枚目の tile(0,0) を 16:9 の領域に拡大表示）
  function buildThumb(source) {
    const thumb = document.createElement('div');
    thumb.className = 'video-card__thumb';
    const sp = source.sprite;
    if (sp && sp.sheets && sp.sheets.length) {
      // columns * 100% の背景サイズで拡大 → tile(0,0) がサムネイル枠に収まる
      thumb.style.backgroundImage = `url("${sp.sheets[0]}")`;
      thumb.style.backgroundSize = `${(sp.columns || 10) * 100}% ${(sp.rows || 10) * 100}%`;
      thumb.style.backgroundPosition = '0 0';
    } else {
      thumb.classList.add('video-card__thumb--placeholder');
    }
    return thumb;
  }

  // ===== Shared button factories =====

  function playButton(source, triggerEl) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary btn-play';
    btn.type = 'button';
    btn.textContent = '▶ 再生';
    btn.addEventListener('click', () => togglePlayer(source.videoId, triggerEl, btn));
    return btn;
  }

  function convertButton(source, triggerEl) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary';
    btn.type = 'button';
    btn.textContent = '変換';
    btn.addEventListener('click', () => triggerConvert(source.filename, source.videoId, triggerEl));
    return btn;
  }

  function disabledBtn(label) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary';
    btn.textContent = label;
    btn.disabled = true;
    return btn;
  }

  // ===== Inline player expansion (works for both views) =====

  async function togglePlayer(videoId, triggerEl, button) {
    if (expanded && expanded.videoId === videoId) { collapseExpanded(); return; }
    collapseExpanded();

    const role = triggerEl.dataset.role; // 'row' or 'card'
    const expansionEl = createExpansionEl(role, triggerEl);
    triggerEl.after(expansionEl);
    triggerEl.classList.add('is-expanded');
    button.textContent = '▼ 閉じる';
    button.classList.add('is-open');

    expanded = { videoId, triggerEl, expansionEl, instance: null, button };

    const mount = expansionEl.querySelector('.inline-player__mount');
    try {
      const instance = await window.HlsPlayer.init(mount, videoId);
      if (!expanded || expanded.videoId !== videoId) { instance.dispose(); return; }
      expanded.instance = instance;
    } catch (err) {
      mount.innerHTML = `<p class="status">再生できません: ${escapeHtml(err.message || String(err))}</p>`;
    }
  }

  function createExpansionEl(role, triggerEl) {
    if (role === 'row') {
      // テーブル行として差し込み、colspan で全幅
      const tr = document.createElement('tr');
      tr.className = 'player-row';
      const td = document.createElement('td');
      td.colSpan = triggerEl.children.length;
      td.appendChild(buildInlineShell());
      tr.appendChild(td);
      return tr;
    }
    // card: grid で grid-column: 1 / -1（CSS 側で付与）
    const div = document.createElement('div');
    div.className = 'player-expansion';
    div.appendChild(buildInlineShell());
    return div;
  }

  function buildInlineShell() {
    const shell = document.createElement('div');
    shell.className = 'inline-player';
    const mount = document.createElement('div');
    mount.className = 'inline-player__mount';
    shell.appendChild(mount);
    return shell;
  }

  function collapseExpanded() {
    if (!expanded) return;
    if (expanded.instance) { try { expanded.instance.dispose(); } catch (_) { /* ignore */ } }
    if (expanded.expansionEl && expanded.expansionEl.parentNode) expanded.expansionEl.remove();
    if (expanded.triggerEl) expanded.triggerEl.classList.remove('is-expanded');
    if (expanded.button) {
      expanded.button.textContent = '▶ 再生';
      expanded.button.classList.remove('is-open');
    }
    expanded = null;
  }

  // ===== Conversion flow =====

  async function triggerConvert(filename, videoId, triggerEl) {
    const actionCell = triggerEl.querySelector('.action-cell');
    const statusCell = triggerEl.querySelector('.status-cell');
    actionCell.innerHTML = '';
    statusCell.innerHTML = '';
    statusCell.appendChild(badge('🚀 開始中…', 'running'));

    try {
      const res = await fetch(`/api/sources/${encodeURIComponent(filename)}/convert`, { method: 'POST' });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);

      pollJob(body.jobId, videoId);
    } catch (err) {
      statusCell.innerHTML = '';
      statusCell.appendChild(badge(`失敗: ${err.message}`, 'error'));
      const retry = document.createElement('button');
      retry.className = 'btn btn-primary';
      retry.textContent = '再試行';
      retry.addEventListener('click', () => triggerConvert(filename, videoId, triggerEl));
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

        const el = document.querySelector(`[data-video-id="${cssEscape(videoId)}"]`);
        if (el) updateFromJob(el, job);

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

  function updateFromJob(el, job) {
    const statusCell = el.querySelector('.status-cell');
    if (!statusCell) return;
    statusCell.innerHTML = '';
    if (job.state === 'pending') {
      statusCell.appendChild(badge('待機中', 'running'));
    } else if (job.state === 'running') {
      statusCell.appendChild(renderProgress(job));
    } else if (job.state === 'completed') {
      statusCell.appendChild(badge('✓ 変換済', 'ok'));
    } else if (job.state === 'failed') {
      statusCell.appendChild(badge(`✗ 失敗: ${job.error || ''}`.slice(0, 80), 'error'));
    }
  }

  function renderProgress(job) {
    const stageLabel = ({
      probe: '解析中', hls: 'HLS変換中', sprite: 'サムネイル生成中',
    })[job.stage] || '処理中';
    const overall = Math.max(0, Math.min(1, job.progress || 0));
    const pct = Math.round(overall * 100);
    const wrap = document.createElement('div');
    wrap.className = 'progress';
    wrap.innerHTML = `
      <div class="progress-track" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
        <div class="progress-bar" style="width: ${pct}%"></div>
      </div>
      <span class="progress-label">${escapeHtml(stageLabel)} <strong>${pct}%</strong></span>
    `;
    return wrap;
  }

  // ===== Utilities =====

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
    let v = n / 1024; let i = 0;
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
