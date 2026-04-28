<script>
  /** @type {string} */
  export let source = ''
  /** @type {{ mode: string|null, confidence: number, weight: number, stale: boolean, agrees: boolean, last_update: string } | null} */
  export let signal = null
  /** @type {string} */
  export let fusedMode = 'idle'
  /** @type {string} */
  export let mColor = '#4a6cf7'

  const SOURCE_META = {
    process:     { label: 'Process',    icon: 'cpu' },
    camera:      { label: 'Camera',     icon: 'video' },
    audio_ml:    { label: 'Audio ML',   icon: 'mic' },
    rule_engine: { label: 'Rules',      icon: 'clock' },
  }

  $: meta = SOURCE_META[source] || { label: source, icon: 'cpu' }
  $: hasData = signal && signal.mode != null
  $: conf = signal?.confidence ?? 0
  $: confPct = Math.round(conf * 100)
  $: agrees = signal?.agrees ?? false
  $: stale = signal?.stale ?? false
</script>

<div
  class="signal-card widget"
  class:stale
  class:no-data={!hasData}
  style="--accent: {mColor}"
>
  <div class="card-header">
    <svg class="card-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      {#if meta.icon === 'cpu'}
        <rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>
      {:else if meta.icon === 'video'}
        <path d="M15 7h1a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-1"/><path d="M23 7l-5 5 5 5V7z"/><path d="M1 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V5z"/>
      {:else if meta.icon === 'mic'}
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/><path d="M8 23h8"/>
      {:else if meta.icon === 'clock'}
        <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
      {:else if meta.icon === 'wifi'}
        <path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" x2="12.01" y1="20" y2="20"/>
      {/if}
    </svg>
    <span class="agree-dot" style="background: {hasData ? (agrees ? '#30c060' : '#f0a030') : 'rgba(255,255,255,0.1)'}"></span>
    <span class="card-label">{meta.label}</span>
  </div>

  {#if hasData}
    <div class="card-mode">{signal.mode}</div>
    <div class="bar-row">
      <div class="bar-track">
        <div
          class="bar-fill"
          style="width: {confPct}%; background: {agrees ? mColor : 'rgba(255,255,255,0.1)'}"
        ></div>
      </div>
      <span class="bar-pct">{confPct}%</span>
    </div>
    <div class="card-weight">wt: {signal.weight?.toFixed(2) ?? '—'}</div>
  {:else}
    <div class="no-data-label">No data</div>
  {/if}

  {#if stale}
    <span class="stale-tag">STALE</span>
  {/if}
</div>

<style>
  .signal-card {
    flex: 1;
    min-width: 120px;
    max-width: 160px;
    padding: 14px 12px 10px;
    position: relative;
    transition: opacity 0.4s ease, border-color 0.3s ease;
  }
  .signal-card.stale {
    opacity: 0.3;
  }
  .signal-card.no-data {
    opacity: 0.5;
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }

  .card-icon {
    width: 16px;
    height: 16px;
    color: rgba(255, 255, 255, 0.5);
    flex-shrink: 0;
  }

  .agree-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
    transition: background 0.3s ease;
  }

  .card-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 1px;
    color: rgba(255, 255, 255, 0.6);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .card-mode {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.75);
    text-transform: capitalize;
    margin-bottom: 8px;
    line-height: 1;
  }

  .bar-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }
  .bar-track {
    flex: 1;
    height: 5px;
    background: rgba(255, 255, 255, 0.06);
    border-radius: 3px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.6s ease, background 0.3s ease;
  }
  .bar-pct {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.45);
    min-width: 28px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .card-weight {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.25);
    font-variant-numeric: tabular-nums;
  }

  .no-data-label {
    text-align: center;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.2);
    padding: 12px 0;
  }

  .stale-tag {
    position: absolute;
    top: 6px;
    right: 6px;
    font-size: 8px;
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 1px;
    color: #f0a030;
    background: rgba(240, 160, 48, 0.12);
    padding: 1px 5px;
    border-radius: 4px;
  }
</style>
