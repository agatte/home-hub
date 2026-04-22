<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, laneMode: string, agrees: boolean, stale: boolean, key: string, label: string, display: string, impact: number }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  // Agreement drives color; impact drives visual weight (stroke + fill opacity).
  $: stroke = node?.agrees ? modeColor(fusedMode) : modeColor(node?.laneMode || 'idle')
  $: impact = Math.max(0, Math.min(1, node?.impact ?? 0.5))
  $: fillAlpha = 0.18 + 0.22 * impact
  $: fill = modeColorSoft(node?.laneMode || 'idle', fillAlpha)
  $: strokeWidth = 1.2 + 1.4 * impact
  $: tooltip = `${node.label}: ${node.display}`

  // Estimate pill width from the display string — SVG has no intrinsic text
  // measurement in templates, so we use a glyph-count heuristic + min clamp.
  $: charCount = (node.display || '').length
  $: pillWidth = Math.max(36, Math.min(110, charCount * 6.2 + 14))
  $: pillHeight = 18
</script>

<g
  class="pip"
  class:stale={node.stale}
  class:agrees={node.agrees}
  transform="translate({node.x}, {node.y})"
>
  <title>{tooltip}</title>
  <rect
    x={-pillWidth / 2}
    y={-pillHeight / 2}
    width={pillWidth}
    height={pillHeight}
    rx={pillHeight / 2}
    ry={pillHeight / 2}
    class="pill"
    fill={fill}
    stroke={stroke}
    stroke-width={strokeWidth}
  />
  {#if node.display}
    <text text-anchor="middle" dominant-baseline="central" class="pill-label">
      {node.display}
    </text>
  {/if}
</g>

<style>
  .pip {
    transition: transform 500ms ease;
    pointer-events: all;
  }
  .pip.stale {
    opacity: 0.4;
  }
  .pill {
    transition: stroke 400ms ease, fill 400ms ease, stroke-width 400ms ease;
    filter: drop-shadow(0 0 4px rgba(0, 0, 0, 0.4));
  }
  .pill-label {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 10.5px;
    font-weight: 500;
    fill: rgba(255, 255, 255, 0.9);
    pointer-events: none;
    user-select: none;
    letter-spacing: 0.2px;
  }
</style>
