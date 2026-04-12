<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { modeColor, modeLabel } from '$lib/theme.js'

  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  let summary = null
  let patterns = null
  let activity = null
  let rules = null
  let loading = true

  async function fetchAll() {
    try {
      const [s, p, a, r] = await Promise.all([
        apiGet('/api/events/summary?days=30'),
        apiGet('/api/events/patterns?days=30'),
        apiGet('/api/events/activity?days=7&limit=20'),
        apiGet('/api/rules/'),
      ])
      summary = s
      patterns = p
      activity = a
      rules = r
    } catch (e) {
      // partial data is fine
    }
    loading = false
  }

  onMount(fetchAll)

  /** @param {number} n */
  function fmtNum(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
    return String(n)
  }

  /** @param {string} iso */
  function fmtTime(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      timeZone: 'America/Indiana/Indianapolis',
    })
  }

  $: modeDistribution = (() => {
    if (!summary?.activity?.modes) return []
    const modes = summary.activity.modes
    const total = Object.values(modes).reduce((a, b) => a + b, 0)
    if (!total) return []
    return Object.entries(modes)
      .map(([mode, count]) => ({ mode, count, pct: Math.round(count / total * 100) }))
      .sort((a, b) => b.count - a.count)
  })()

  $: donutGradient = (() => {
    if (!modeDistribution.length) return ''
    let offset = 0
    return modeDistribution.map(({ mode, pct }) => {
      const color = modeColor(mode)
      const start = (offset * 3.6).toFixed(1)
      offset += pct
      const end = (offset * 3.6).toFixed(1)
      return `${color} ${start}deg ${end}deg`
    }).join(', ')
  })()

  $: topMode = modeDistribution.length ? modeDistribution[0] : null

  $: overrideRate = patterns?.overrides
    ? Math.round(patterns.overrides.override_rate * 100)
    : 0

  async function toggleRule(id, enabled) {
    try {
      await fetch(`/api/rules/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !enabled }),
      })
      const r = await apiGet('/api/rules/')
      rules = r
    } catch { /* ignore */ }
  }

  async function forceRegenerate() {
    try {
      await apiPost('/api/rules/regenerate')
      const r = await apiGet('/api/rules/')
      rules = r
    } catch { /* ignore */ }
  }
</script>

<main class="analytics-page">
  {#if loading}
    <div class="analytics-loading">Loading analytics...</div>
  {:else}
    <div class="page-grid">

      <!-- Mode Distribution Donut -->
      <section class="widget">
        <h2 class="widget-title">Mode Distribution (30 days)</h2>
        {#if modeDistribution.length}
          <div class="analytics-donut-container">
            <div class="analytics-donut" style="background: conic-gradient({donutGradient})">
              <div class="analytics-donut-hole">
                <span class="analytics-donut-total">{summary?.activity?.total_transitions || 0}</span>
                <span class="analytics-donut-label">transitions</span>
              </div>
            </div>
            <div class="analytics-legend">
              {#each modeDistribution.filter(m => m.pct >= 2) as { mode, count, pct }}
                <div class="analytics-legend-item">
                  <span class="analytics-legend-dot" style="background: {modeColor(mode)}"></span>
                  <span class="analytics-legend-name">{modeLabel(mode)}</span>
                  <span class="analytics-legend-value">{pct}%</span>
                </div>
              {/each}
            </div>
          </div>
        {:else}
          <p class="analytics-empty">No activity data yet</p>
        {/if}
      </section>

      <!-- Quick Stats -->
      <section class="widget">
        <h2 class="widget-title">Quick Stats</h2>
        <div class="analytics-stats-grid">
          <div class="analytics-stat">
            <span class="analytics-stat-value">{fmtNum(summary?.activity?.total_transitions || 0)}</span>
            <span class="analytics-stat-label">Mode Changes</span>
          </div>
          <div class="analytics-stat">
            <span class="analytics-stat-value">{overrideRate}%</span>
            <span class="analytics-stat-label">Manual Override</span>
          </div>
          <div class="analytics-stat">
            <span class="analytics-stat-value" style="color: {topMode ? modeColor(topMode.mode) : 'inherit'}">{topMode ? modeLabel(topMode.mode) : '—'}</span>
            <span class="analytics-stat-label">Top Mode</span>
          </div>
          <div class="analytics-stat">
            <span class="analytics-stat-value">{fmtNum(summary?.scenes?.total_activations || 0)}</span>
            <span class="analytics-stat-label">Scenes Used</span>
          </div>
        </div>
      </section>

      <!-- Hourly Patterns -->
      <section class="widget widget-full">
        <h2 class="widget-title">Hourly Patterns</h2>
        {#if patterns?.by_hour?.length}
          <div class="analytics-hours">
            {#each patterns.by_hour as { hour, mode, pct }}
              <div class="analytics-hour-row">
                <span class="analytics-hour-label">{hour.toString().padStart(2, '0')}:00</span>
                <div class="analytics-hour-bar-bg">
                  <div
                    class="analytics-hour-bar"
                    style="width: {pct}%; background: {modeColor(mode)}"
                  ></div>
                </div>
                <span class="analytics-hour-mode" style="color: {modeColor(mode)}">{modeLabel(mode)}</span>
                <span class="analytics-hour-pct">{pct}%</span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="analytics-empty">Not enough data for hourly patterns</p>
        {/if}
      </section>

      <!-- Learned Rules -->
      <section class="widget">
        <h2 class="widget-title">
          Learned Rules
          <button class="analytics-regen-btn" on:click={forceRegenerate}>Regenerate</button>
        </h2>
        {#if rules?.rules?.length}
          <div class="analytics-rules-list">
            {#each rules.rules as rule}
              <div class="analytics-rule-row">
                <span class="analytics-rule-time">{DAY_NAMES[rule.day_of_week]} {rule.hour.toString().padStart(2, '0')}:00</span>
                <span class="analytics-rule-mode" style="color: {modeColor(rule.predicted_mode)}">{modeLabel(rule.predicted_mode)}</span>
                <span class="analytics-rule-conf">{rule.confidence}%</span>
                <button
                  class="analytics-rule-toggle"
                  class:enabled={rule.enabled}
                  on:click={() => toggleRule(rule.id, rule.enabled)}
                >{rule.enabled ? 'On' : 'Off'}</button>
              </div>
            {/each}
          </div>
        {:else}
          <p class="analytics-empty">No rules yet — the engine needs more data (70%+ confidence, 3+ samples per time slot)</p>
        {/if}
      </section>

      <!-- Recent Activity -->
      <section class="widget">
        <h2 class="widget-title">Recent Activity (7 days)</h2>
        {#if activity?.events?.length}
          <div class="analytics-activity-list">
            {#each activity.events as event}
              <div class="analytics-activity-row">
                <span class="analytics-activity-dot" style="background: {modeColor(event.mode)}"></span>
                <span class="analytics-activity-mode">{modeLabel(event.mode)}</span>
                <span class="analytics-activity-source">{event.source}</span>
                <span class="analytics-activity-duration">{event.duration_minutes ? event.duration_minutes + 'm' : '—'}</span>
                <span class="analytics-activity-time">{fmtTime(event.timestamp)}</span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="analytics-empty">No recent activity</p>
        {/if}
      </section>

      <!-- Top Favorites & Scenes -->
      <section class="widget widget-full">
        <h2 class="widget-title">Top Sonos & Scenes</h2>
        <div class="analytics-top-grid">
          <div>
            <h3 class="analytics-sub-title">Sonos Favorites</h3>
            {#if summary?.sonos?.top_favorites?.length}
              {#each summary.sonos.top_favorites as fav}
                <div class="analytics-top-row">
                  <span class="analytics-top-name">{fav.title}</span>
                  <span class="analytics-top-count">{fav.count} plays</span>
                </div>
              {/each}
            {:else}
              <p class="analytics-empty">No Sonos data</p>
            {/if}
          </div>
          <div>
            <h3 class="analytics-sub-title">Scenes</h3>
            {#if summary?.scenes?.top_scenes?.length}
              {#each summary.scenes.top_scenes as scene}
                <div class="analytics-top-row">
                  <span class="analytics-top-name">{scene.name}</span>
                  <span class="analytics-top-count">{scene.count} uses</span>
                </div>
              {/each}
            {:else}
              <p class="analytics-empty">No scene data</p>
            {/if}
          </div>
        </div>
      </section>

    </div>
  {/if}
</main>

<style>
  .analytics-page {
    padding: 24px 20px 100px;
    max-width: 960px;
    margin: 0 auto;
  }

  .analytics-loading {
    text-align: center;
    padding: 60px 0;
    color: var(--text-muted);
    font-family: var(--font-body);
  }

  .analytics-empty {
    color: var(--text-muted);
    font-size: 13px;
    margin: 8px 0 0;
  }

  /* Donut chart */
  .analytics-donut-container {
    display: flex;
    align-items: center;
    gap: 24px;
  }
  .analytics-donut {
    width: 120px;
    height: 120px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .analytics-donut-hole {
    width: 70px;
    height: 70px;
    border-radius: 50%;
    background: var(--bg-base);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .analytics-donut-total {
    font-family: var(--font-display);
    font-size: 22px;
    color: var(--text-primary);
    line-height: 1;
  }
  .analytics-donut-label {
    font-size: 9px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .analytics-legend {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .analytics-legend-item {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }
  .analytics-legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .analytics-legend-name {
    color: var(--text-secondary);
    flex: 1;
  }
  .analytics-legend-value {
    color: var(--text-muted);
    font-size: 12px;
  }

  /* Stats grid */
  .analytics-stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .analytics-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 12px 0;
  }
  .analytics-stat-value {
    font-family: var(--font-display);
    font-size: 28px;
    color: var(--text-primary);
    line-height: 1.1;
  }
  .analytics-stat-label {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
  }

  /* Hourly patterns */
  .analytics-hours {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 400px;
    overflow-y: auto;
  }
  .analytics-hour-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }
  .analytics-hour-label {
    width: 42px;
    color: var(--text-muted);
    font-size: 12px;
    flex-shrink: 0;
  }
  .analytics-hour-bar-bg {
    flex: 1;
    height: 14px;
    background: rgba(255, 255, 255, 0.04);
    border-radius: 4px;
    overflow: hidden;
  }
  .analytics-hour-bar {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
    min-width: 2px;
  }
  .analytics-hour-mode {
    width: 60px;
    font-size: 11px;
    text-align: right;
    flex-shrink: 0;
  }
  .analytics-hour-pct {
    width: 32px;
    text-align: right;
    color: var(--text-muted);
    font-size: 11px;
    flex-shrink: 0;
  }

  /* Rules list */
  .analytics-rules-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .analytics-rule-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
  }
  .analytics-rule-row:last-child { border-bottom: none; }
  .analytics-rule-time {
    color: var(--text-secondary);
    width: 70px;
    flex-shrink: 0;
  }
  .analytics-rule-mode {
    flex: 1;
    font-weight: 600;
  }
  .analytics-rule-conf {
    color: var(--text-muted);
    font-size: 12px;
    width: 36px;
    text-align: right;
  }
  .analytics-rule-toggle {
    padding: 2px 10px;
    border-radius: 10px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .analytics-rule-toggle.enabled {
    border-color: var(--accent, #4a6cf7);
    color: var(--accent, #4a6cf7);
  }
  .analytics-rule-toggle:hover {
    background: rgba(255, 255, 255, 0.06);
  }
  .analytics-regen-btn {
    float: right;
    padding: 2px 8px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    font-size: 10px;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .analytics-regen-btn:hover {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary);
  }

  /* Activity list */
  .analytics-activity-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
    max-height: 360px;
    overflow-y: auto;
  }
  .analytics-activity-row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    padding: 5px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  }
  .analytics-activity-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .analytics-activity-mode {
    color: var(--text-primary);
    width: 60px;
    flex-shrink: 0;
  }
  .analytics-activity-source {
    color: var(--text-muted);
    width: 55px;
    flex-shrink: 0;
    font-size: 11px;
  }
  .analytics-activity-duration {
    color: var(--text-secondary);
    width: 40px;
    text-align: right;
    flex-shrink: 0;
  }
  .analytics-activity-time {
    color: var(--text-muted);
    font-size: 11px;
    margin-left: auto;
  }

  /* Top favorites/scenes */
  .analytics-top-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  .analytics-sub-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    margin: 0 0 8px;
    font-weight: 400;
  }
  .analytics-top-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 13px;
    padding: 4px 0;
  }
  .analytics-top-name {
    color: var(--text-secondary);
  }
  .analytics-top-count {
    color: var(--text-muted);
    font-size: 12px;
  }

  @media (max-width: 900px) {
    .analytics-donut-container { flex-direction: column; }
    .analytics-top-grid { grid-template-columns: 1fr; gap: 16px; }
  }
</style>
