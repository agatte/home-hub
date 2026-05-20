<script>
  import { apiPost } from '$lib/api.js'
  import { automation } from '$lib/stores/automation.js'
  import SettingButton from './SettingButton.svelte'

  /** @typedef {{event: string, label: string, icon: string, hint: string, accent: string}} TestEvent */

  /** @type {TestEvent[]} */
  const EVENTS = [
    { event: 'pregame',         label: 'Pregame T-60',  icon: '🏟️', hint: 'Pre-kickoff ramp',                    accent: 'rgba(74, 108, 247, 0.22)' },
    { event: 'kickoff',         label: 'Kickoff',       icon: '🦵', hint: 'Open / quarter starts',               accent: 'rgba(74, 108, 247, 0.22)' },
    { event: 'touchdown',       label: 'Touchdown',     icon: '🏈', hint: '6 points + extra-point setup',        accent: 'rgba(34, 211, 145, 0.28)' },
    { event: 'extra_point_good',label: 'Extra Point',   icon: '✅', hint: 'PAT good',                            accent: 'rgba(34, 211, 145, 0.20)' },
    { event: 'two_point_conv',  label: '2-pt Conv',     icon: '🎯', hint: 'Two-point conversion',                accent: 'rgba(34, 211, 145, 0.20)' },
    { event: 'field_goal',      label: 'Field Goal',    icon: '🥅', hint: '3 points',                            accent: 'rgba(74, 108, 247, 0.22)' },
    { event: 'safety',          label: 'Safety',        icon: '🛡️', hint: '2 points (defense)',                  accent: 'rgba(34, 211, 145, 0.20)' },
    { event: 'defensive_td',    label: 'Defensive TD',  icon: '⚡', hint: 'Pick-six / fumble return',            accent: 'rgba(251, 191, 36, 0.22)' },
    { event: 'momentum',        label: 'Momentum',      icon: '📈', hint: 'WPA swing on non-scoring play',       accent: 'rgba(140, 100, 200, 0.22)' },
    { event: 'end_of_game_win', label: 'Final · WIN',   icon: '🏆', hint: 'Closing sequence (win)',              accent: 'rgba(34, 211, 145, 0.32)' },
    { event: 'end_of_game_loss',label: 'Final · LOSS',  icon: '💔', hint: 'Closing sequence (loss)',             accent: 'rgba(248, 113, 113, 0.22)' },
  ]

  /** @type {Record<string, {at: number, status: 'ok' | 'error', detail?: string}>} */
  let lastFired = {}
  /** @type {string | null} */
  let firing = null
  /** @type {string | null} */
  let lastError = null

  $: currentMode = $automation?.mode
  $: gamedayActive = currentMode === 'gameday' || currentMode === 'pregameday'

  /** @param {string} event */
  async function fire(event) {
    firing = event
    lastError = null
    try {
      const path = event === 'pregame'
        ? '/api/gameday/test/pregame'
        : `/api/gameday/test/${event}`
      const body = event === 'pregame' ? { matchup: 'TEST vs IND', kickoff_in_seconds: 60 } : {}
      const resp = /** @type {any} */ (await apiPost(path, body))
      lastFired = {
        ...lastFired,
        [event]: { at: Date.now(), status: resp?.status === 'ok' ? 'ok' : 'error' },
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Fire failed'
      lastFired = { ...lastFired, [event]: { at: Date.now(), status: 'error', detail: msg } }
      lastError = msg
    } finally {
      firing = null
    }
  }

  /** @param {number} ts */
  function relTime(ts) {
    const s = Math.floor((Date.now() - ts) / 1000)
    if (s < 5) return 'just now'
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    return `${Math.floor(s / 3600)}h ago`
  }
</script>

<div class="gameday-grid">
  {#if !gamedayActive}
    <div class="mode-warning">
      <span class="mode-warning-icon">⚠</span>
      <div class="mode-warning-text">
        Current mode is <strong>{currentMode || 'unknown'}</strong> — test fires log to the journal but the
        celebration orchestrator only runs full lighting + TTS sequences in <strong>gameday</strong> mode.
      </div>
    </div>
  {/if}

  <div class="grid">
    {#each EVENTS as ev (ev.event)}
      <div class="fire-card" style:--card-accent={ev.accent}>
        <div class="fire-head">
          <span class="fire-icon">{ev.icon}</span>
          <div class="fire-meta">
            <span class="fire-label">{ev.label}</span>
            <span class="fire-hint">{ev.hint}</span>
          </div>
        </div>
        <div class="fire-foot">
          {#if lastFired[ev.event]}
            <span class="fire-status" class:err={lastFired[ev.event].status === 'error'}>
              {lastFired[ev.event].status === 'ok' ? 'Fired' : 'Failed'} · {relTime(lastFired[ev.event].at)}
            </span>
          {:else}
            <span class="fire-status muted">Not fired yet</span>
          {/if}
          <SettingButton
            variant="accent"
            loading={firing === ev.event}
            disabled={firing !== null && firing !== ev.event}
            on:click={() => fire(ev.event)}
          >
            {firing === ev.event ? 'Firing…' : 'Fire'}
          </SettingButton>
        </div>
      </div>
    {/each}
  </div>

  {#if lastError}
    <p class="fire-error">{lastError}</p>
  {/if}
</div>

<style>
  .gameday-grid {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .mode-warning {
    display: flex;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 10px;
    background: rgba(251, 191, 36, 0.08);
    border: 1px solid rgba(251, 191, 36, 0.28);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    line-height: 1.5;
  }

  .mode-warning-icon {
    flex-shrink: 0;
    color: rgb(251, 191, 36);
    font-size: 14px;
  }

  .mode-warning strong {
    color: var(--text-primary);
    font-weight: 600;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
  }

  .fire-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border-radius: var(--radius-sm, 10px);
    background: var(--card-accent, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--border);
    transition: border-color 0.2s;
  }

  .fire-card:hover {
    border-color: var(--border-hover);
  }

  .fire-head {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .fire-icon {
    font-size: 22px;
    line-height: 1;
    flex-shrink: 0;
  }

  .fire-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .fire-label {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .fire-hint {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .fire-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: auto;
  }

  .fire-status {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--success);
  }

  .fire-status.muted {
    color: var(--text-muted);
  }

  .fire-status.err {
    color: var(--danger);
  }

  .fire-error {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--danger);
    margin: 0;
  }
</style>
