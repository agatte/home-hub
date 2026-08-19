<script>
  import { onDestroy, onMount } from 'svelte'
  import { Activity, CheckCircle2, AlertTriangle } from 'lucide-svelte'
  import { automation, activityLabel, houseStateLabel } from '$lib/stores/automation.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { modeColor } from '$lib/theme.js'

  /** @type {Record<string, string>} */
  const SOURCE_LABELS = {
    process: 'PC activity',
    time: 'Schedule',
    schedule: 'Schedule',
    confidence_fusion: 'Apartment context',
    fusion: 'Apartment context',
    physical_context_relax: 'Room context',
    ambient_relax: 'Room context',
  }

  /** @param {string | null | undefined} value */
  function titleCase(value) {
    if (!value) return ''
    return String(value)
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase())
  }

  /** @param {string | null | undefined} source @param {boolean} manualOverride */
  function sourceLabel(source, manualOverride) {
    if (manualOverride) return 'Manual override'
    const detail = source ? SOURCE_LABELS[source] : null
    return detail ? `Automatic · ${detail}` : 'Automatic'
  }

  let currentTime = ''
  /** @type {ReturnType<typeof setInterval> | null} */
  let clockInterval = null

  function updateClock() {
    currentTime = new Date().toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  }

  onMount(() => {
    updateClock()
    clockInterval = setInterval(updateClock, 10000)
  })

  onDestroy(() => {
    if (clockInterval) clearInterval(clockInterval)
  })

  $: house = houseStateLabel($automation.house_state) || 'Connecting'
  $: activity = activityLabel($automation.activity)
  $: headline = activity || house
  $: eyebrow = activity ? house : 'House state'
  $: source = sourceLabel($automation.source, $automation.manual_override)
  $: period = titleCase($automation.time_period)
  $: accent = modeColor($automation.mode)
  $: unavailable = [
    !$connected ? 'Server' : null,
    !$deviceStatus.hue ? 'Hue' : null,
    !$deviceStatus.sonos ? 'Sonos' : null,
  ].filter(Boolean)
  $: healthy = unavailable.length === 0
  $: healthText = healthy
    ? 'All systems online'
    : `${unavailable.join(', ')} ${unavailable.length === 1 ? 'is' : 'are'} unavailable`
</script>

<section class="home-context" style="--context-accent: {accent}" aria-labelledby="home-context-title">
  <div class="context-glow" aria-hidden="true"></div>

  <div class="context-copy">
    <div class="context-eyebrow-row">
      <span class="context-eyebrow">{eyebrow}</span>
      {#if currentTime}
        <span class="context-separator" aria-hidden="true">•</span>
        <time class="context-time">{currentTime}</time>
      {/if}
    </div>

    <div class="context-title-row">
      <Activity size={22} strokeWidth={1.5} aria-hidden="true" />
      <h1 id="home-context-title">{headline}</h1>
    </div>

    <div class="context-meta">
      <span class="context-control">{source}</span>
      {#if period}
        <span class="context-meta-dot" aria-hidden="true">•</span>
        <span>{period}</span>
      {/if}
      {#if $automation.dnd?.enabled}
        <span class="context-meta-dot" aria-hidden="true">•</span>
        <span class="context-dnd">
          DND
          {#if $automation.dnd.minutes_remaining > 0}
            · {$automation.dnd.minutes_remaining}m
          {/if}
        </span>
      {/if}
    </div>
  </div>

  <div class:degraded={!healthy} class="context-health" role={healthy ? undefined : 'status'}>
    {#if healthy}
      <CheckCircle2 size={18} strokeWidth={1.7} aria-hidden="true" />
    {:else}
      <AlertTriangle size={18} strokeWidth={1.7} aria-hidden="true" />
    {/if}
    <div class="health-copy">
      <span class="health-label">Apartment systems</span>
      <strong>{healthText}</strong>
    </div>
  </div>
</section>

<style>
  .home-context {
    position: relative;
    overflow: hidden;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 28px;
    align-items: center;
    min-height: 168px;
    margin-bottom: 16px;
    padding: 28px 30px;
    border: 1px solid color-mix(in srgb, var(--context-accent) 18%, var(--border));
    border-radius: 20px;
    background:
      linear-gradient(135deg, color-mix(in srgb, var(--context-accent) 8%, transparent), transparent 48%),
      rgba(9, 9, 14, 0.72);
    backdrop-filter: blur(18px) saturate(1.15);
    -webkit-backdrop-filter: blur(18px) saturate(1.15);
  }

  .context-glow {
    position: absolute;
    width: 260px;
    height: 260px;
    top: -165px;
    left: -70px;
    border-radius: 50%;
    background: var(--context-accent);
    filter: blur(80px);
    opacity: 0.12;
    pointer-events: none;
  }

  .context-copy,
  .context-health {
    position: relative;
    z-index: 1;
  }

  .context-copy {
    min-width: 0;
  }

  .context-eyebrow-row,
  .context-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .context-eyebrow {
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--context-accent) 72%, var(--text-primary));
  }

  .context-time,
  .context-separator,
  .context-meta,
  .context-meta-dot {
    color: var(--text-muted);
  }

  .context-time {
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  .context-title-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 9px;
    color: var(--context-accent);
  }

  .context-title-row h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: clamp(42px, 5vw, 64px);
    font-weight: 400;
    line-height: 0.95;
    letter-spacing: 0.055em;
    text-transform: uppercase;
    color: var(--text-primary);
  }

  .context-meta {
    flex-wrap: wrap;
    margin-top: 12px;
    font-size: 13px;
  }

  .context-control {
    color: var(--text-secondary);
  }

  .context-dnd {
    color: var(--warning);
  }

  .context-health {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 180px;
    padding: 12px 14px;
    border: 1px solid rgba(52, 211, 153, 0.14);
    border-radius: 12px;
    background: rgba(52, 211, 153, 0.045);
    color: var(--success);
  }

  .context-health.degraded {
    border-color: rgba(248, 113, 113, 0.2);
    background: rgba(248, 113, 113, 0.06);
    color: var(--danger);
  }

  .health-copy {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .health-label {
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
  }

  .health-copy strong {
    font-size: 12px;
    font-weight: 600;
    line-height: 1.25;
    color: var(--text-secondary);
  }

  .context-health.degraded .health-copy strong {
    color: var(--danger);
  }

  @media (max-width: 700px) {
    .home-context {
      grid-template-columns: minmax(0, 1fr);
      gap: 18px;
      min-height: 0;
      padding: 22px;
    }

    .context-health {
      width: fit-content;
      min-width: 0;
    }
  }

  @media (max-width: 480px) {
    .home-context {
      padding: 20px 18px;
      border-radius: 16px;
    }

    .context-title-row h1 {
      font-size: 42px;
    }

    .context-title-row {
      gap: 10px;
    }

    .context-meta {
      font-size: 12px;
    }
  }
</style>
