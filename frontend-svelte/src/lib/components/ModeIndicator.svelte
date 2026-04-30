<script>
  import { automation } from '$lib/stores/automation.js'
  import { MODE_CONFIG, modeColor } from '$lib/theme.js'

  $: config = MODE_CONFIG[$automation.mode] || MODE_CONFIG.idle
  $: color = modeColor($automation.mode)
  $: dnd = $automation.dnd?.enabled ?? false
  $: dndRemaining = $automation.dnd?.minutes_remaining ?? 0
  $: dndLabel = dndRemaining >= 60
    ? `DND • ${Math.floor(dndRemaining / 60)}h ${dndRemaining % 60}m`
    : `DND • ${dndRemaining}m`
</script>

<div class="mode-indicator-compact">
  <div class="mode-dot-ring" style="border-color: {color}; box-shadow: 0 0 8px {color}40"></div>
  <div class="mode-detail">
    <span class="mode-label-text" style="color: {color}">
      {config.label}
    </span>
    {#if dnd}
      <span class="dnd-badge" title="Do Not Disturb active — autonomous changes blocked">
        {dndLabel}
      </span>
    {/if}
  </div>
</div>

<style>
  .mode-indicator-compact {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .mode-detail {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .mode-dot-ring {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid;
    flex-shrink: 0;
    animation: dotPulse 3s ease-in-out infinite;
  }

  @keyframes dotPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  @media (prefers-reduced-motion: reduce) {
    .mode-dot-ring { animation: none; }
  }

  .mode-label-text {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
  }

  .dnd-badge {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    padding: 2px 7px;
    border-radius: 999px;
    color: rgba(255, 255, 255, 0.85);
    background: rgba(140, 100, 200, 0.22);
    border: 1px solid rgba(140, 100, 200, 0.45);
    white-space: nowrap;
  }
</style>
