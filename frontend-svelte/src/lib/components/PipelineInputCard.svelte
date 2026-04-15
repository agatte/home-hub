<script>
  /** @type {{ key: string, label: string, icon: string, isWinner: boolean, [k: string]: any }} */
  export let input
  /** @type {string} */
  export let modeColor = '#4a6cf7'

  /** Build a summary string for each input type */
  $: summary = (() => {
    switch (input.key) {
      case 'manual_override':
        return input.mode ? `Mode: ${input.mode}` : 'Inactive'
      case 'activity':
        return input.mode
          ? `${input.mode} (${input.source})`
          : 'None'
      case 'ambient':
        return input.mode || 'Quiet'
      case 'screen_sync':
        return input.active
          ? `Light ${input.target_light} (${input.source || 'desktop'})`
          : 'Off'
      case 'time_of_day':
        return `${input.period} · ${input.schedule_type}`
      case 'weather':
        return input.condition || 'Clear'
      case 'brightness':
        return `${input.multiplier ?? 1.0}x`
      case 'scene_override':
        return input.scene_id ? `Scene active` : 'None'
      default:
        return 'Active'
    }
  })()
</script>

<div
  class="input-card widget"
  class:winner={input.isWinner}
  style="--accent: {modeColor}"
>
  <div class="card-icon">
    <svg class="lucide-placeholder" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      {#if input.icon === 'hand'}
        <path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/><path d="M14 10V4a2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 13"/>
      {:else if input.icon === 'cpu'}
        <rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>
      {:else if input.icon === 'mic'}
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>
      {:else if input.icon === 'monitor-smartphone'}
        <path d="M18 8V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h8"/><path d="M10 19v-3.96 3.15"/><path d="M7 19h5"/><rect width="6" height="10" x="16" y="12" rx="2"/>
      {:else if input.icon === 'clock'}
        <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
      {:else if input.icon === 'cloud'}
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
      {:else if input.icon === 'sun'}
        <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
      {:else if input.icon === 'palette'}
        <circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>
      {:else}
        <circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>
      {/if}
    </svg>
  </div>
  <div class="card-label">{input.label}</div>
  <div class="card-value">{summary}</div>
</div>

<style>
  .input-card {
    flex: 1;
    min-width: 120px;
    max-width: 180px;
    padding: 14px 12px;
    text-align: center;
    transition: border-color 0.4s ease, box-shadow 0.4s ease;
  }
  .input-card.winner {
    border-color: var(--accent, rgba(255,255,255,0.2));
    box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 25%, transparent);
  }

  .card-icon {
    display: flex;
    justify-content: center;
    margin-bottom: 8px;
  }
  .card-icon svg {
    width: 20px;
    height: 20px;
    color: rgba(255, 255, 255, 0.5);
    transition: color 0.3s ease;
  }
  .winner .card-icon svg {
    color: var(--accent);
  }

  .card-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 1px;
    color: rgba(255, 255, 255, 0.6);
    margin-bottom: 4px;
  }
  .winner .card-label {
    color: rgba(255, 255, 255, 0.9);
  }

  .card-value {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.4);
    text-transform: capitalize;
    line-height: 1.3;
  }
</style>
