<script>
  import { modeColor, modeColorSoft, modeLabel } from '$lib/theme.js'

  /** @type {{ x: number, y: number, mode: string, agreement: number, timePeriod: string, autoApply: boolean }} */
  export let node
  /** @type {number} */
  export let confidence = 0

  $: mode = node?.mode || 'idle'
  $: color = modeColor(mode)
  $: label = modeLabel(mode).toUpperCase()
  $: confPct = Math.round((confidence || 0) * 100)
  $: haloColor = modeColorSoft(mode, 0.35)
</script>

<g
  class="nucleus"
  class:auto-apply={node?.autoApply}
  transform="translate({node.x}, {node.y})"
  style="--mode-color: {color}; --mode-halo: {haloColor};"
>
  <!-- Outer breathing ring -->
  <circle r="104" class="ring ring-outer" />
  <!-- Mid glow -->
  <circle r="82" class="ring ring-mid" />
  <!-- Core disc -->
  <circle r="68" class="core" fill={color} />

  <!-- Label + confidence -->
  <text class="mode-label" y="-6" text-anchor="middle">{label}</text>
  <text class="mode-conf" y="22" text-anchor="middle">{confPct}%</text>
</g>

<style>
  .nucleus {
    filter: drop-shadow(0 0 12px var(--mode-halo));
    transition: filter 400ms ease;
  }
  .ring {
    fill: none;
    stroke: var(--mode-color);
    transform-origin: center;
    transform-box: fill-box;
  }
  .ring-outer {
    stroke-opacity: 0.15;
    stroke-width: 1.5;
    animation: breathe 4s ease-in-out infinite;
  }
  .ring-mid {
    stroke-opacity: 0.3;
    stroke-width: 1;
    animation: breatheMid 4s ease-in-out infinite;
  }
  .core {
    opacity: 0.95;
    transition: fill 600ms ease;
    filter: drop-shadow(0 0 18px var(--mode-halo));
  }
  .nucleus.auto-apply .core {
    animation: corePulse 1.6s ease-in-out infinite;
  }

  @keyframes breathe {
    0%, 100% { transform: scale(1.00); stroke-opacity: 0.10; }
    50%      { transform: scale(1.05); stroke-opacity: 0.22; }
  }
  @keyframes breatheMid {
    0%, 100% { transform: scale(0.98); stroke-opacity: 0.2; }
    50%      { transform: scale(1.03); stroke-opacity: 0.4; }
  }
  @keyframes corePulse {
    0%, 100% { opacity: 0.95; }
    50%      { opacity: 0.75; }
  }

  .mode-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 30px;
    letter-spacing: 4px;
    fill: rgba(0, 0, 0, 0.85);
    pointer-events: none;
  }
  .mode-conf {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 18px;
    letter-spacing: 1.5px;
    fill: rgba(0, 0, 0, 0.62);
    pointer-events: none;
  }
</style>
