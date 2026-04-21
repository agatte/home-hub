<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'

  const TARGET_PER_DAY = 2.0

  let overrideRate = null
  let compare = null
  let loading = true

  async function fetchAll() {
    loading = true
    try {
      const [o, c] = await Promise.all([
        apiGet('/api/learning/override-rate'),
        apiGet('/api/learning/compare?days=14'),
      ])
      overrideRate = o
      compare = c
    } catch {
      // errors surface via toast; keep last-known state
    }
    loading = false
  }

  onMount(fetchAll)

  /** @param {number} v */
  function rateColor(v) {
    if (v == null) return 'var(--text-muted)'
    if (v < 1.5) return '#4ade80'
    if (v < 2.0) return '#fbbf24'
    return '#f87171'
  }

  /** @param {number} v */
  function rateFill(v) {
    if (v == null) return 0
    return Math.min(100, (v / (TARGET_PER_DAY * 2)) * 100)
  }

  /** @param {number} v */
  function fmtRate(v) {
    if (v == null) return '—'
    return v.toFixed(2)
  }

  /** @param {number} acc */
  function fmtPct(acc) {
    if (acc == null) return '—'
    return (acc * 100).toFixed(1) + '%'
  }

  const STRATEGY_LABELS = {
    fusion: 'Confidence Fusion',
    rule_engine: 'Rule Engine Only',
    process: 'Process Priority',
  }

  const STRATEGY_ORDER = ['fusion', 'process', 'rule_engine']

  $: strategies = (() => {
    if (!compare?.strategies) return []
    return STRATEGY_ORDER
      .filter((k) => compare.strategies[k])
      .map((k) => ({ key: k, label: STRATEGY_LABELS[k], ...compare.strategies[k] }))
  })()

  $: bestKey = (() => {
    if (!strategies.length) return null
    const eligible = strategies.filter((s) => s.total >= 20)
    if (!eligible.length) return null
    return eligible.reduce((a, b) => (a.accuracy >= b.accuracy ? a : b)).key
  })()
</script>

<section class="widget widget-full">
  <h2 class="widget-title">
    Autonomy Gate
    <button class="refresh-btn" on:click={fetchAll} disabled={loading}>
      {loading ? '…' : 'Refresh'}
    </button>
  </h2>

  <!-- Override rate section -->
  <div class="gate-section">
    <div class="section-label">
      Manual Overrides per Day
      <span class="section-target">Phase 3 exit gate: &lt; {TARGET_PER_DAY} / day sustained 30 days</span>
    </div>

    <div class="rate-grid">
      {#each ['7d', '30d'] as window}
        {@const w = overrideRate?.[window]}
        <div class="rate-cell">
          <div class="rate-window">{window === '7d' ? '7-day' : '30-day'}</div>
          <div class="rate-value" style="color: {rateColor(w?.overrides_per_day)}">
            {fmtRate(w?.overrides_per_day)}
            <span class="rate-unit">/ day</span>
          </div>
          <div class="rate-bar-bg">
            <div
              class="rate-bar"
              style="width: {rateFill(w?.overrides_per_day)}%; background: {rateColor(w?.overrides_per_day)}"
            ></div>
            <div class="rate-target-line" style="left: 50%"></div>
          </div>
          <div class="rate-detail">
            {#if w}
              {w.overrides} overrides · {w.total_manual} manual · {w.cold_switches} cold
            {:else}
              —
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>

  <!-- Strategy comparison section -->
  <div class="gate-section">
    <div class="section-label">
      Strategy A/B ({compare?.window_days ?? 14}-day window)
      <span class="section-target">On the same backfilled fusion-decision rows</span>
    </div>

    {#if strategies.length}
      <div class="strategy-list">
        {#each strategies as s}
          <div class="strategy-row" class:best={s.key === bestKey}>
            <span class="strategy-label">
              {s.label}
              {#if s.key === bestKey}<span class="best-badge">BEST</span>{/if}
            </span>
            <div class="strategy-bar-bg">
              <div
                class="strategy-bar"
                style="width: {s.accuracy * 100}%; background: {s.key === bestKey ? '#4ade80' : 'rgba(255,255,255,0.35)'}"
              ></div>
            </div>
            <span class="strategy-acc">{fmtPct(s.accuracy)}</span>
            <span class="strategy-n">
              {#if s.total < 20}
                <span class="insufficient">n={s.total}, sparse</span>
              {:else}
                n={s.total}
              {/if}
            </span>
          </div>
        {/each}
      </div>
    {:else}
      <p class="empty">No comparison data yet — fusion needs backfilled rows to score.</p>
    {/if}
  </div>

  <!-- Thresholds section -->
  <div class="gate-section thresholds-section">
    <div class="section-label">
      Current Autonomy Thresholds
      <span class="section-target">Tunable after 30 days of shadow+backfill data accrue</span>
    </div>
    <div class="threshold-grid">
      <div class="threshold-cell">
        <span class="threshold-label">Auto-apply</span>
        <span class="threshold-value">95%</span>
        <span class="threshold-note">when idle/away</span>
      </div>
      <div class="threshold-cell">
        <span class="threshold-label">Stale override</span>
        <span class="threshold-value">92%</span>
        <span class="threshold-note">+ 80% signal agreement</span>
      </div>
    </div>
  </div>
</section>

<style>
  .widget {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    backdrop-filter: blur(12px);
  }
  .widget-full {
    grid-column: 1 / -1;
  }
  .widget-title {
    font-family: var(--font-display, 'Bebas Neue'), sans-serif;
    font-size: 16px;
    letter-spacing: 2px;
    color: var(--text-primary);
    margin: 0 0 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .refresh-btn {
    padding: 2px 10px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    font-size: 10px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .refresh-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary);
  }
  .refresh-btn:disabled {
    cursor: wait;
    opacity: 0.5;
  }

  .gate-section {
    margin-bottom: 20px;
  }
  .gate-section:last-child {
    margin-bottom: 0;
  }

  .section-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }
  .section-target {
    text-transform: none;
    letter-spacing: 0;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.25);
  }

  /* Rate grid */
  .rate-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  .rate-cell {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .rate-window {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .rate-value {
    font-family: var(--font-display, 'Bebas Neue'), sans-serif;
    font-size: 32px;
    line-height: 1;
  }
  .rate-unit {
    font-size: 12px;
    color: var(--text-muted);
    letter-spacing: 1px;
    margin-left: 4px;
  }
  .rate-bar-bg {
    position: relative;
    height: 6px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 3px;
    overflow: hidden;
    margin-top: 4px;
  }
  .rate-bar {
    height: 100%;
    transition: width 0.3s ease;
    border-radius: 3px;
  }
  .rate-target-line {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 1px;
    background: rgba(255, 255, 255, 0.35);
  }
  .rate-detail {
    font-size: 11px;
    color: var(--text-muted);
  }

  /* Strategy list */
  .strategy-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .strategy-row {
    display: grid;
    grid-template-columns: 140px 1fr 52px 80px;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    padding: 4px 0;
  }
  .strategy-label {
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .strategy-row.best .strategy-label {
    color: var(--text-primary);
  }
  .best-badge {
    font-size: 9px;
    letter-spacing: 1px;
    padding: 1px 6px;
    border-radius: 3px;
    background: rgba(74, 222, 128, 0.15);
    color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.3);
  }
  .strategy-bar-bg {
    height: 10px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
    overflow: hidden;
  }
  .strategy-bar {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
    min-width: 2px;
  }
  .strategy-acc {
    color: var(--text-primary);
    font-family: var(--font-display, 'Bebas Neue'), sans-serif;
    font-size: 16px;
    text-align: right;
    letter-spacing: 1px;
  }
  .strategy-n {
    color: var(--text-muted);
    font-size: 11px;
    text-align: right;
  }
  .insufficient {
    color: #fbbf24;
  }

  .empty {
    color: var(--text-muted);
    font-size: 12px;
    margin: 4px 0 0;
  }

  /* Thresholds */
  .thresholds-section {
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }
  .threshold-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }
  .threshold-cell {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .threshold-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
  }
  .threshold-value {
    font-family: var(--font-display, 'Bebas Neue'), sans-serif;
    font-size: 22px;
    color: var(--text-primary);
    line-height: 1.1;
  }
  .threshold-note {
    font-size: 11px;
    color: var(--text-muted);
  }

  @media (max-width: 700px) {
    .rate-grid {
      grid-template-columns: 1fr;
      gap: 16px;
    }
    .strategy-row {
      grid-template-columns: 1fr 52px;
      grid-template-areas:
        'label acc'
        'bar   bar'
        'n     n';
      gap: 4px;
    }
    .strategy-label { grid-area: label; }
    .strategy-bar-bg { grid-area: bar; }
    .strategy-acc { grid-area: acc; }
    .strategy-n { grid-area: n; text-align: left; }
    .threshold-grid {
      grid-template-columns: 1fr;
      gap: 12px;
    }
  }
</style>
