<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, key: string, label: string, display: string, active: boolean }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  $: tint = modeColorSoft(fusedMode, node.active ? 0.22 : 0.08)
  $: stroke = node.active ? modeColor(fusedMode) : 'rgba(255,255,255,0.25)'
</script>

<g
  class="context"
  class:active={node.active}
  transform="translate({node.x}, {node.y})"
>
  <title>{node.label}: {node.display}</title>

  <!-- Outer dashed ring distinguishes this as "context, not vote" -->
  <circle r="36" class="ring" stroke={stroke} />
  <!-- Solid fill disc -->
  <circle r="32" class="fill" fill={tint} stroke={stroke} />

  <!-- Label above, display below -->
  <text y="-6" text-anchor="middle" class="label">{node.label.toUpperCase()}</text>
  <text y="12" text-anchor="middle" class="display">{node.display}</text>
</g>

<style>
  .context {
    transition: transform 700ms ease;
    opacity: 0.75;
  }
  .context.active {
    opacity: 1;
  }

  .ring {
    fill: none;
    stroke-width: 1.2;
    stroke-dasharray: 3 5;
    opacity: 0.55;
  }
  .context.active .ring {
    opacity: 0.85;
    animation: contextPulse 6s ease-in-out infinite;
  }
  @keyframes contextPulse {
    0%, 100% { transform: scale(1.0); opacity: 0.65; }
    50%      { transform: scale(1.03); opacity: 0.95; }
  }

  .fill {
    stroke-width: 1;
    transition: fill 500ms ease, stroke 500ms ease;
  }

  .label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 1.8px;
    fill: rgba(255, 255, 255, 0.65);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.6);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .display {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 12px;
    font-weight: 500;
    fill: rgba(255, 255, 255, 0.88);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.7);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .context:not(.active) .display {
    fill: rgba(255, 255, 255, 0.5);
  }
</style>
