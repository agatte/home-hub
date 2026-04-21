<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, laneMode: string, agrees: boolean, stale: boolean, key: string, label: string, display: string, impact: number }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  $: color = node?.agrees ? modeColor(fusedMode) : modeColor(node?.laneMode || 'idle')
  $: radius = 12 + 14 * (node?.impact ?? 0.5)
  $: tooltip = `${node.label}: ${node.display}`
  $: softFill = modeColorSoft(node?.laneMode || 'idle', 0.3)
</script>

<g
  class="pip"
  class:stale={node.stale}
  class:agrees={node.agrees}
  transform="translate({node.x}, {node.y})"
>
  <title>{tooltip}</title>
  <circle r={radius} class="disc" fill={softFill} stroke={color} />
  <!-- Always show the display value under the pip -->
  {#if node.display}
    <text
      y={radius + 13}
      text-anchor="middle"
      class="pip-label"
    >{node.display}</text>
  {/if}
</g>

<style>
  .pip {
    transition: transform 500ms ease;
    pointer-events: all;
  }
  .pip.stale {
    opacity: 0.35;
  }
  .disc {
    stroke-width: 1.8;
    transition: r 500ms ease, stroke 400ms ease;
    filter: drop-shadow(0 0 5px rgba(0, 0, 0, 0.45));
  }
  .pip.agrees .disc {
    stroke-width: 2.4;
  }
  .pip-label {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 11px;
    font-weight: 500;
    fill: rgba(255, 255, 255, 0.78);
    pointer-events: none;
    user-select: none;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.7);
    stroke-width: 3;
    stroke-linejoin: round;
  }
</style>
