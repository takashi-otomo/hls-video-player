<script lang="ts">
  import { api } from './api';

  let logText = '';
  let status: any = null;
  let jobId: string | null = null;
  let ws: WebSocket | null = null;
  let logEl: HTMLPreElement;

  async function start(type: 'hls' | 'ts-merge') {
    stop();
    logText = '';
    status = { state: 'queued' };
    try {
      const { job_id } = await api.startConvert({ type, workers: 2 });
      jobId = job_id;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(
        `${proto}://${location.host}/api/convert/jobs/${encodeURIComponent(job_id)}/logs`,
      );
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === 'log') {
          logText += m.text;
          queueMicrotask(() => {
            if (logEl) logEl.scrollTop = logEl.scrollHeight;
          });
        } else if (m.type === 'status') {
          status = m;
        }
      };
      ws.onerror = () => {
        logText += '\n[WebSocket エラー]\n';
      };
    } catch (e: any) {
      logText += `起動失敗: ${e.message}\n`;
      status = { state: 'failed', error: e.message };
    }
  }

  function stop() {
    if (ws) {
      ws.close();
      ws = null;
    }
  }
</script>

<div class="convert-panel">
  <div class="actions">
    <button
      class="primary"
      on:click={() => start('hls')}
      disabled={status?.state === 'running'}
    >
      🎬 HLS 変換実行
    </button>
    <button
      on:click={() => start('ts-merge')}
      disabled={status?.state === 'running'}
    >
      🔗 TS 結合実行
    </button>
    {#if status}
      <span class="state" class:running={status.state === 'running'}>
        {status.state}
        {#if status.progress != null}
          ({Math.round(status.progress * 100)}%)
        {/if}
        {#if status.error}— {status.error}{/if}
      </span>
    {/if}
  </div>
  {#if logText}
    <pre class="log" bind:this={logEl}>{logText}</pre>
  {/if}
</div>

<style>
  .convert-panel { padding: 0.75rem 1rem; border-top: 1px solid var(--border); }
  .actions { display: flex; gap: 0.5rem; align-items: center; }
  .primary { background: var(--accent-strong); color: #fff; border: none; }
  .state { color: var(--muted); font-size: 0.85rem; }
  .state.running { color: var(--gold); }
  .log {
    margin: 0.5rem 0 0;
    max-height: 280px;
    overflow-y: auto;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-family: Menlo, monospace;
    font-size: 11px;
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-all;
  }
</style>
