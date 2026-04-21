<script>
  import { modeColor } from '$lib/theme.js'

  /** @type {string} */
  export let mode = 'idle'
  /** @type {string} */
  export let modeLabelText = 'Idle'
  /** @type {number} */
  export let confidence = 0

  $: confPct = Math.round((confidence || 0) * 100)
  $: dotColor = modeColor(mode)
</script>

<div class="legend">
  <div class="row primary">
    <span class="dot" style="background: {dotColor}"></span>
    <span class="mode">{modeLabelText}</span>
    <span class="pct">{confPct}%</span>
  </div>
  <div class="row hint">
    <span>inner = voters</span>
    <span class="sep">·</span>
    <span>outer = context</span>
    <span class="sep">·</span>
    <span>distance = inverse weight</span>
  </div>
</div>

<style>
  .legend {
    position: absolute;
    bottom: 8px;
    left: 12px;
    font-family: 'Source Sans 3', sans-serif;
    pointer-events: none;
    user-select: none;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
  }
  .row.primary {
    gap: 8px;
  }
  .mode {
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 2px;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.7);
  }
  .pct {
    color: rgba(255, 255, 255, 0.4);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .hint {
    color: rgba(255, 255, 255, 0.25);
    margin-top: 2px;
  }
  .sep {
    opacity: 0.5;
  }
</style>
