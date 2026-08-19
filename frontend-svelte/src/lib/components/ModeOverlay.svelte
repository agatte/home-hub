<script>
  import { automation, activityLabel, houseStateLabel } from '$lib/stores/automation.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { modeColor } from '$lib/theme.js'
  import StatusDot from './StatusDot.svelte'
  import { onMount, onDestroy } from 'svelte'

  function overlayStateLabel(state) {
    return houseStateLabel(state.house_state) || 'HomeHub'
  }

  let displayedState = overlayStateLabel($automation)
  let modeChars = displayedState.toUpperCase().split('')
  let animating = false
  let currentTime = ''

  function updateClock() {
    const now = new Date()
    currentTime = now.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  }

  let clockInterval

  onMount(() => {
    updateClock()
    clockInterval = setInterval(updateClock, 10000)
  })

  onDestroy(() => {
    clearInterval(clockInterval)
  })

  $: currentState = overlayStateLabel($automation)
  $: if (currentState !== displayedState) {
    animating = true
    displayedState = currentState
    modeChars = displayedState.toUpperCase().split('')
    setTimeout(() => { animating = false }, modeChars.length * 30 + 300)
  }

  $: currentActivity = activityLabel($automation.activity)
  $: source = $automation.manual_override
    ? 'Manual override'
    : `Auto (${$automation.source || 'time'})`
  $: context = currentActivity ? `${currentActivity} • ${source}` : source

  $: color = modeColor($automation.mode)
</script>

<div class="mode-overlay">
  <div class="mode-overlay-top">
    <h1 class="mode-name" style="color: {color}">
      {#each modeChars as char, i}
        <span
          class="mode-char"
          class:animating
          style="animation-delay: {i * 30}ms"
        >{char}</span>
      {/each}
    </h1>
    <div class="mode-time">{currentTime}</div>
  </div>
  <div class="mode-source">{context}</div>
  <div class="mode-status">
    <StatusDot active={$connected} label="Server" />
    <StatusDot active={$deviceStatus.hue} label="Hue" />
    <StatusDot active={$deviceStatus.sonos} label="Sonos" />
  </div>
</div>

<style>
  .mode-overlay {
    position: fixed;
    top: calc(20px + env(safe-area-inset-top, 0px));
    left: calc(24px + env(safe-area-inset-left, 0px));
    z-index: 40;
    pointer-events: none;
    user-select: none;
  }

  .mode-overlay-top {
    display: flex;
    align-items: baseline;
    gap: 16px;
  }

  .mode-name {
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 400;
    letter-spacing: 0.12em;
    line-height: 1;
    margin: 0;
  }

  .mode-char {
    display: inline-block;
  }

  .mode-char.animating {
    animation: charFlyIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  }

  @keyframes charFlyIn {
    from {
      opacity: 0;
      transform: translateY(12px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .mode-char.animating {
      animation: none;
    }
  }

  .mode-time {
    font-family: var(--font-body);
    font-size: 14px;
    color: var(--text-muted);
    font-weight: 300;
  }

  .mode-source {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 4px;
    letter-spacing: 0.02em;
  }

  .mode-status {
    display: flex;
    gap: 8px;
    margin-top: 8px;
    pointer-events: auto;
  }

  @media (max-width: 768px) {
    .mode-overlay {
      top: calc(12px + env(safe-area-inset-top, 0px));
      left: calc(16px + env(safe-area-inset-left, 0px));
    }
    .mode-name {
      font-size: 28px;
    }
  }

  @media (max-width: 480px) {
    .mode-overlay {
      display: none;
    }
  }
</style>
