<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ source: any, target: any, weight: number, agrees: boolean, stale: boolean, hasData: boolean }} */
  export let link
  /** @type {string} */
  export let fusedMode = 'idle'

  $: color = link?.agrees ? modeColor(fusedMode) : modeColorSoft(fusedMode, 0.4)
  $: opacity = link?.stale ? 0.08 : 0.18 + 0.55 * (link?.weight || 0)
  $: width = 0.8 + 2.8 * (link?.weight || 0)
  $: sx = link.source?.x ?? 0
  $: sy = link.source?.y ?? 0
  $: tx = link.target?.x ?? 0
  $: ty = link.target?.y ?? 0
</script>

<line
  x1={sx}
  y1={sy}
  x2={tx}
  y2={ty}
  stroke={color}
  stroke-width={width}
  stroke-opacity={opacity}
  stroke-linecap="round"
  class:agrees={link.agrees}
  class:stale={link.stale}
  class="edge"
/>

<style>
  .edge {
    transition: stroke 400ms ease, stroke-opacity 400ms ease;
  }
  .edge.agrees {
    stroke-dasharray: 2 6;
    animation: flow 6s linear infinite;
  }
  @keyframes flow {
    from { stroke-dashoffset: 0; }
    to   { stroke-dashoffset: -80; }
  }
</style>
