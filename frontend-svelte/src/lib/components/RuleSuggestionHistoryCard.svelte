<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { modeColor, modeLabel } from '$lib/theme.js'

  /**
   * @typedef {Object} SuggestionRow
   * @property {number} id
   * @property {number} rule_id
   * @property {string} fired_at
   * @property {string} predicted_mode
   * @property {number} confidence
   * @property {number} sample_count
   * @property {string|null} current_mode_at_fire
   * @property {string} status
   * @property {string|null} resolved_at
   * @property {string|null} resolved_source
   */

  /** @type {SuggestionRow[] | null} */
  let history = null
  let loading = true

  onMount(async () => {
    try {
      const res = /** @type {any} */ (await apiGet('/api/rules/suggestions?limit=50'))
      history = res?.suggestions ?? []
    } catch {
      history = []
    } finally {
      loading = false
    }
  })

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
</script>

<section class="widget">
  <h2 class="widget-title">Suggestion History</h2>
  {#if loading}
    <p class="hist-empty">Loading…</p>
  {:else if history?.length}
    <div class="hist-list">
      {#each history as row (row.id)}
        <div class="hist-row">
          <span class="hist-time">{timeAgo(row.fired_at)}</span>
          <span class="hist-mode" style="color: {modeColor(row.predicted_mode)}">{modeLabel(row.predicted_mode)}</span>
          <span class="hist-conf">{row.confidence}%</span>
          <span class="hist-status hist-status-{row.status}">{row.status}</span>
        </div>
      {/each}
    </div>
  {:else}
    <p class="hist-empty">
      No suggestions yet — the engine hasn't nudged you. Suggestions fire when an enabled rule matches the current time slot and you're idle.
    </p>
  {/if}
</section>

<style>
  .hist-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 400px;
    overflow-y: auto;
  }
  .hist-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  }
  .hist-row:last-child { border-bottom: none; }
  .hist-time {
    color: var(--text-secondary);
    width: 70px;
    flex-shrink: 0;
    font-size: 12px;
  }
  .hist-mode {
    flex: 1;
    font-weight: 600;
  }
  .hist-conf {
    color: var(--text-muted);
    font-size: 12px;
    width: 36px;
    text-align: right;
  }
  .hist-status {
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border: 1px solid transparent;
  }
  .hist-status-accepted {
    color: #4ade80;
    border-color: rgba(74, 222, 128, 0.4);
    background: rgba(74, 222, 128, 0.08);
  }
  .hist-status-dismissed {
    color: var(--text-muted);
    border-color: var(--border, rgba(255, 255, 255, 0.1));
  }
  .hist-status-expired {
    color: var(--text-muted);
    border-color: var(--border, rgba(255, 255, 255, 0.08));
    opacity: 0.75;
  }
  .hist-status-superseded {
    color: var(--text-muted);
    border-color: var(--border, rgba(255, 255, 255, 0.08));
    opacity: 0.75;
  }
  .hist-status-pending {
    color: var(--accent, #4a6cf7);
    border-color: color-mix(in srgb, var(--accent, #4a6cf7) 50%, transparent);
    background: color-mix(in srgb, var(--accent, #4a6cf7) 12%, transparent);
  }
  .hist-empty {
    color: var(--text-muted);
    font-size: 13px;
    margin: 8px 0 0;
  }
</style>
