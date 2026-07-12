<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
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
   * @property {string} [kind]
   * @property {any} [payload]
   */

  /** @type {SuggestionRow[] | null} */
  let history = null
  let loading = true

  onMount(loadHistory)

  async function loadHistory() {
    loading = true
    try {
      const res = /** @type {any} */ (await apiGet('/api/rules/suggestions?limit=50'))
      history = res?.suggestions ?? []
    } catch {
      history = []
    } finally {
      loading = false
    }
  }

  async function resolveBrightness(row, action) {
    try {
      await apiPost(`/api/rules/brightness-suggestion/${action}/${row.id}`)
      await loadHistory()
    } catch {
      await loadHistory()
    }
  }

  function isPendingBrightness(row) {
    return row.status === 'pending' && row.kind === 'brightness' && row.payload
  }

  function weatherLabel(cls) {
    return ({
      thunderstorm: 'thunderstorm',
      rain: 'rainy',
      clouds: 'overcast',
      snow: 'snowy',
      golden_hour: 'golden-hour',
      clear: 'clear',
    })[cls] || cls
  }

  function roomLabel(room) {
    return ({
      bedroom: 'Bedroom',
      kitchen: 'Kitchen',
      living_room: 'Living room',
    })[room] || room
  }

  function suggestionLabel(row) {
    const payload = row.payload || {}
    if (row.kind === 'brightness' && payload.scope === 'room') {
      const pct = payload.target_pct ?? Math.round((Number(payload.suggested_bri || 0) / 254) * 100)
      return `${roomLabel(payload.room)} ${modeLabel(payload.mode || row.predicted_mode)} · ${weatherLabel(payload.weather_class)} · ~${pct}%`
    }
    if (row.kind === 'brightness' && payload.light_id) {
      const pct = Math.round((Number(payload.suggested_bri || 0) / 254) * 100)
      return `L${payload.light_id} ${modeLabel(payload.mode || row.predicted_mode)} · ${weatherLabel(payload.weather_class)} · ~${pct}%`
    }
    return modeLabel(row.predicted_mode)
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
</script>

<section class="widget">
  <h2 class="widget-title">Suggestion History</h2>
  {#if loading}
    <p class="hist-empty">Loading…</p>
  {:else if history?.length}
    <div class="hist-list">
      {#each history as row (row.id)}
        <div class="hist-row" class:hist-row-pending={isPendingBrightness(row)}>
          <span class="hist-time">{timeAgo(row.fired_at)}</span>
          <span class="hist-mode" style="color: {modeColor(row.predicted_mode)}">{suggestionLabel(row)}</span>
          <span class="hist-conf">{row.confidence}%</span>
          <span class="hist-status hist-status-{row.status}">{row.status}</span>
          {#if isPendingBrightness(row)}
            <span class="hist-actions">
              <button class="hist-action hist-action-accept" on:click={() => resolveBrightness(row, 'accept')}>Apply</button>
              <button class="hist-action" on:click={() => resolveBrightness(row, 'dismiss')} aria-label="Dismiss suggestion">Dismiss</button>
            </span>
          {/if}
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
  .hist-row-pending {
    padding: 8px 0;
  }
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
  .hist-actions {
    display: inline-flex;
    gap: 6px;
    flex-shrink: 0;
  }
  .hist-action {
    border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-primary, #fff);
    cursor: pointer;
    font-size: 11px;
    padding: 4px 8px;
  }
  .hist-action:hover {
    border-color: var(--accent, #4a6cf7);
  }
  .hist-action-accept {
    color: var(--accent, #4a6cf7);
    background: color-mix(in srgb, var(--accent, #4a6cf7) 16%, transparent);
  }
  .hist-empty {
    color: var(--text-muted);
    font-size: 13px;
    margin: 8px 0 0;
  }
</style>
