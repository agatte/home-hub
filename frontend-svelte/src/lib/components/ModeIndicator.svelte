<script>
  import { automation } from '$lib/stores/automation.js'
  import { MODE_CONFIG, modeColor } from '$lib/theme.js'

  $: config = MODE_CONFIG[$automation.mode] || MODE_CONFIG.idle
  $: color = modeColor($automation.mode)
</script>

<div class="mode-indicator-compact">
  <div class="mode-dot-ring" style="border-color: {color}; box-shadow: 0 0 8px {color}40"></div>
  <div class="mode-detail">
    <span class="mode-label-text" style="color: {color}">
      {config.label}
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
</style>
