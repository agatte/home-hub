<script>
  import { automation, activityLabel, houseStateLabel } from '$lib/stores/automation.js'
  import { modeColor } from '$lib/theme.js'

  $: houseLabel = houseStateLabel($automation.house_state)
  $: currentActivityLabel = activityLabel($automation.activity)
  $: color = modeColor($automation.mode)
  $: dnd = $automation.dnd?.enabled ?? false
  $: dndRemaining = $automation.dnd?.minutes_remaining ?? 0
  $: dndLabel = dndRemaining >= 60
    ? `DND • ${Math.floor(dndRemaining / 60)}h ${dndRemaining % 60}m`
    : `DND • ${dndRemaining}m`
</script>

<div class="state-indicator-compact">
  <div class="state-dot-ring" style="border-color: {color}; box-shadow: 0 0 8px {color}40"></div>
  <div class="state-detail">
    <div class="state-summary">
      <span class="house-state-text" style="color: {color}">
        {houseLabel || 'State unavailable'}
      </span>
      {#if currentActivityLabel}
        <span class="state-separator" aria-hidden="true">•</span>
        <span class="activity-text">{currentActivityLabel}</span>
      {/if}
    </div>
    {#if dnd}
      <span class="dnd-badge" title="Do Not Disturb active — autonomous changes blocked">
        {dndLabel}
      </span>
    {/if}
  </div>
</div>

<style>
  .state-indicator-compact {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .state-detail,
  .state-summary {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .state-dot-ring {
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
    .state-dot-ring { animation: none; }
  }

  .house-state-text,
  .activity-text {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
  }

  .activity-text,
  .state-separator {
    color: var(--text-muted);
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

  @media (max-width: 480px) {
    .state-detail {
      align-items: flex-start;
      flex-direction: column;
      gap: 5px;
    }
  }
</style>
