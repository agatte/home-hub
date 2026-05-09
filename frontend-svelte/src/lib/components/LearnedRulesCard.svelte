<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { modeColor, modeLabel } from '$lib/theme.js'

  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  /** @type {{rules?: Array<{id: number, day_of_week: number, hour: number, predicted_mode: string, confidence: number, enabled: boolean}>} | null} */
  let rules = null
  let loading = true

  onMount(async () => {
    try {
      rules = /** @type {any} */ (await apiGet('/api/rules/'))
    } catch {
      rules = { rules: [] }
    } finally {
      loading = false
    }
  })

  /** @param {number} id @param {boolean} enabled */
  async function toggleRule(id, enabled) {
    try {
      await fetch(`/api/rules/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled }),
      })
      rules = /** @type {any} */ (await apiGet('/api/rules/'))
    } catch {
      // ignore — surfaces in next reload
    }
  }

  async function forceRegenerate() {
    try {
      await apiPost('/api/rules/regenerate')
      rules = /** @type {any} */ (await apiGet('/api/rules/'))
    } catch {
      // ignore
    }
  }
</script>

<section class="widget">
  <h2 class="widget-title">
    Learned Rules
    <button class="rules-regen-btn" on:click={forceRegenerate}>Regenerate</button>
  </h2>
  {#if loading}
    <p class="rules-empty">Loading…</p>
  {:else if rules?.rules?.length}
    <div class="rules-list">
      {#each rules.rules as rule (rule.id)}
        <div class="rule-row">
          <span class="rule-time">{DAY_NAMES[rule.day_of_week]} {rule.hour.toString().padStart(2, '0')}:00</span>
          <span class="rule-mode" style="color: {modeColor(rule.predicted_mode)}">{modeLabel(rule.predicted_mode)}</span>
          <span class="rule-conf">{rule.confidence}%</span>
          <button
            class="rule-toggle"
            class:enabled={rule.enabled}
            on:click={() => toggleRule(rule.id, rule.enabled)}
          >{rule.enabled ? 'On' : 'Off'}</button>
        </div>
      {/each}
    </div>
  {:else}
    <p class="rules-empty">
      No rules yet — the engine needs more data (70%+ confidence, 3+ samples per time slot).
    </p>
  {/if}
</section>

<style>
  .rules-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 400px;
    overflow-y: auto;
  }
  .rule-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border, rgba(255, 255, 255, 0.06));
  }
  .rule-row:last-child { border-bottom: none; }
  .rule-time {
    color: var(--text-secondary);
    width: 70px;
    flex-shrink: 0;
  }
  .rule-mode {
    flex: 1;
    font-weight: 600;
  }
  .rule-conf {
    color: var(--text-muted);
    font-size: 12px;
    width: 36px;
    text-align: right;
  }
  .rule-toggle {
    padding: 2px 10px;
    border-radius: 10px;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    background: transparent;
    color: var(--text-muted);
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .rule-toggle.enabled {
    border-color: var(--accent, #4a6cf7);
    color: var(--accent, #4a6cf7);
  }
  .rule-toggle:hover {
    background: rgba(255, 255, 255, 0.06);
  }
  .rules-regen-btn {
    float: right;
    padding: 2px 8px;
    border-radius: 8px;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
    background: transparent;
    color: var(--text-muted);
    font-size: 10px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .rules-regen-btn:hover {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary);
  }
  .rules-empty {
    color: var(--text-muted);
    font-size: 13px;
    margin: 8px 0 0;
  }
</style>
