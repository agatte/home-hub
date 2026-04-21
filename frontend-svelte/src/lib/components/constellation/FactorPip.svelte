<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, laneMode: string, agrees: boolean, stale: boolean, key: string, label: string, display: string, impact: number }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  $: color = node?.agrees ? modeColor(fusedMode) : modeColor(node?.laneMode || 'idle')
  $: radius = 6 + 8 * (node?.impact ?? 0.5)
  $: tooltip = `${node.label}: ${node.display}`
  $: softFill = modeColorSoft(node?.laneMode || 'idle', 0.25)
</script>

<g
  class="pip"
  class:stale={node.stale}
  class:agrees={node.agrees}
  transform="translate({node.x}, {node.y})"
>
  <title>{tooltip}</title>
  <circle r={radius} class="disc" fill={softFill} stroke={color} />
  <!-- Tiny display label below the pip; only show when pip is big enough to not feel crowded -->
  {#if radius >= 10 && node.display}
    <text
      y={radius + 10}
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
    opacity: 0.3;
  }
  .disc {
    stroke-width: 1.2;
    transition: r 400ms ease, stroke 400ms ease;
    filter: drop-shadow(0 0 3px rgba(0, 0, 0, 0.3));
  }
  .pip.agrees .disc {
    stroke-width: 1.6;
  }
  .pip-label {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 9px;
    fill: rgba(255, 255, 255, 0.45);
    pointer-events: none;
    user-select: none;
  }
</style>
