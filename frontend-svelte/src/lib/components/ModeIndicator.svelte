<script>
  import { automation } from '$lib/stores/automation.js'
  import { MODE_CONFIG } from '$lib/theme.js'

  const SOCIAL_STYLE_LABELS = {
    color_cycle: 'Color Cycle',
    club: 'Club',
    rave: 'Rave',
    fire_and_ice: 'Fire & Ice',
  }

  $: config = MODE_CONFIG[$automation.mode] || MODE_CONFIG.idle
  $: showSocialDetail = $automation.mode === 'social' && $automation.social_style
  $: sourceLabel = $automation.manual_override
    ? 'Manual'
    : $automation.source === 'time'
      ? 'Auto (time)'
      : `Auto (${$automation.source})`
</script>

<div class="mode-indicator">
  <span class="mode-icon">{config.icon}</span>
  <div class="mode-info">
    <span class="mode-label" style="color: {config.color}">
      {config.label}
      {#if showSocialDetail}
        <span class="mode-sub-label"> — {SOCIAL_STYLE_LABELS[$automation.social_style ?? ''] || $automation.social_style}</span>
      {/if}
    </span>
    <span class="mode-source">{sourceLabel}</span>
  </div>
  <div class="mode-dot" style="background: {config.color}; box-shadow: 0 0 8px {config.color}"></div>
</div>
