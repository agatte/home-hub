<script>
  import { automation } from '$lib/stores/automation.js'
  import { MODE_CONFIG, modeColor } from '$lib/theme.js'

  const SOCIAL_STYLE_LABELS = {
    color_cycle: 'Color Cycle',
    club: 'Club',
    rave: 'Rave',
    fire_and_ice: 'Fire & Ice',
  }

  $: config = MODE_CONFIG[$automation.mode] || MODE_CONFIG.idle
  $: showSocialDetail = $automation.mode === 'social' && $automation.social_style
  $: color = modeColor($automation.mode)
</script>

<div class="mode-indicator-compact">
  <div class="mode-dot-ring" style="border-color: {color}; box-shadow: 0 0 8px {color}40"></div>
  <div class="mode-detail">
    <span class="mode-label-text" style="color: {color}">
      {config.label}
      {#if showSocialDetail}
        <span class="mode-sub"> — {SOCIAL_STYLE_LABELS[$automation.social_style ?? ''] || $automation.social_style}</span>
      {/if}
    </span>
  </div>
</div>

<style>
  .mode-indicator-compact {
    display: flex;
    align-items: center;
    gap: 10px;
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

  .mode-sub {
    font-weight: 400;
    color: var(--text-secondary);
  }
</style>
