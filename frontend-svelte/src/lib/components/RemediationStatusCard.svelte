<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'

  /**
   * @typedef {Object} RemediationRow
   * @property {number} id
   * @property {string} timestamp
   * @property {string} action
   * @property {string|null} source
   * @property {string} tier
   * @property {string} result
   * @property {string|null} diagnosis_ref
   * @property {string|null} detail
   * @property {boolean} reverted
   */

  /** @type {any} */
  let status = null
  let loading = true

  onMount(async () => {
    try {
      status = await apiGet('/api/remediation/status')
    } catch {
      status = null
    } finally {
      loading = false
    }
  })

  $: mode = status?.mode ?? 'disabled'
  $: recent = /** @type {RemediationRow[]} */ (status?.recent ?? [])
  $: autoToday = status?.auto_executed_last_24h ?? 0
  $: maxAuto = status?.max_auto_per_day ?? 0

  const MODE_LABEL = {
    autonomous: 'Autonomous',
    propose_only: 'Propose-only',
    disabled: 'Disabled',
  }

  /** @param {string} iso */
  function timeAgo(iso) {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const diffSec = Math.max(0, Math.floor((now - then) / 1000))
    if (diffSec < 60) return `${diffSec}s ago`
    const min = Math.floor(diffSec / 60)
    if (min < 60) return `${min}m ago`
    const hr = Math.floor(min / 60)
    if (hr < 24) return `${hr}h ago`
    const day = Math.floor(hr / 24)
    return `${day}d ago`
  }

  /** @param {string} action */
  function actionLabel(action) {
    return action.replace(/_/g, ' ')
  }
</script>

<section class="widget">
  <div class="rem-head">
    <h2 class="widget-title">Remediation</h2>
    <span class="rem-mode rem-mode-{mode}">{MODE_LABEL[mode] ?? mode}</span>
  </div>

  {#if loading}
    <p class="rem-empty">Loading…</p>
  {:else if !status}
    <p class="rem-empty">Status unavailable.</p>
  {:else}
    <p class="rem-sub">
      {#if mode === 'propose_only'}
        Recommends fixes when a source goes bad — never acts on its own. {autoToday}/{maxAuto} auto-fixes used today.
      {:else if mode === 'autonomous'}
        May auto-execute whitelisted fixes. {autoToday}/{maxAuto} used in the last 24h.
      {:else}
        Subsystem off — no monitoring-driven fixes or proposals.
      {/if}
    </p>

    {#if recent.length}
      <div class="rem-list">
        {#each recent as row (row.id)}
          <div class="rem-row" title={row.detail ?? ''}>
            <span class="rem-time">{timeAgo(row.timestamp)}</span>
            <span class="rem-action">{actionLabel(row.action)}</span>
            <span class="rem-result rem-result-{row.result}">{row.result}</span>
          </div>
        {/each}
      </div>
    {:else}
      <p class="rem-empty">
        No proposals yet — nothing has needed remediation. Entries appear here when a source goes untrusted and the watchdog proposes (or, if autonomous, applies) a fix.
      </p>
    {/if}
  {/if}
</section>

<style>
  .rem-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .rem-mode {
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: 1px solid transparent;
  }
  .rem-mode-propose_only {
    color: var(--accent, #4a6cf7);
    border-color: color-mix(in srgb, var(--accent, #4a6cf7) 50%, transparent);
    background: color-mix(in srgb, var(--accent, #4a6cf7) 12%, transparent);
  }
  .rem-mode-autonomous {
    color: #4ade80;
    border-color: rgba(74, 222, 128, 0.4);
    background: rgba(74, 222, 128, 0.08);
  }
  .rem-mode-disabled {
    color: var(--text-muted);
    border-color: var(--border, rgba(255, 255, 255, 0.1));
  }
  .rem-sub {
    color: var(--text-secondary);
    font-size: 12.5px;
    margin: 6px 0 10px;
  }
  .rem-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 400px;
    overflow-y: auto;
  }
  .rem-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  }
  .rem-row:last-child { border-bottom: none; }
  .rem-time {
    color: var(--text-secondary);
    width: 70px;
    flex-shrink: 0;
    font-size: 12px;
  }
  .rem-action {
    flex: 1;
    font-weight: 600;
    text-transform: capitalize;
  }
  .rem-result {
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: 1px solid transparent;
  }
  .rem-result-executed {
    color: #4ade80;
    border-color: rgba(74, 222, 128, 0.4);
    background: rgba(74, 222, 128, 0.08);
  }
  .rem-result-proposed {
    color: var(--accent, #4a6cf7);
    border-color: color-mix(in srgb, var(--accent, #4a6cf7) 50%, transparent);
    background: color-mix(in srgb, var(--accent, #4a6cf7) 12%, transparent);
  }
  .rem-result-skipped {
    color: var(--text-muted);
    border-color: var(--border, rgba(255, 255, 255, 0.1));
  }
  .rem-result-error {
    color: #e25c5c;
    border-color: rgba(226, 92, 92, 0.45);
    background: rgba(226, 92, 92, 0.08);
  }
  .rem-empty {
    color: var(--text-muted);
    font-size: 13px;
    margin: 8px 0 0;
  }
</style>
