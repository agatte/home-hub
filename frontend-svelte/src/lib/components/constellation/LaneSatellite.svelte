<script>
  import { Cpu, Video, Mic, Brain, Clock, Wifi } from 'lucide-svelte'
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, lane: string, label: string, mode: string | null, weight: number, agrees: boolean, stale: boolean, hasData: boolean, confidence: number, lastUpdate: string | null, icon: string }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  const ICON_MAP = {
    cpu: Cpu,
    video: Video,
    mic: Mic,
    brain: Brain,
    clock: Clock,
    wifi: Wifi,
  }

  $: laneMode = node?.mode || 'idle'
  $: color = node?.hasData ? modeColor(laneMode) : 'rgba(255,255,255,0.25)'
  $: outline = node?.agrees ? modeColor(fusedMode) : modeColorSoft(laneMode, 0.55)
  $: radius = node?.stale ? 38 : 52
  $: IconCmp = ICON_MAP[node?.icon] || Cpu

  // Icon sits above center; label inside disc below center.
  $: iconSize = node?.stale ? 18 : 22
</script>

<g
  class="lane"
  class:stale={node.stale}
  class:no-data={!node.hasData}
  class:agrees={node.agrees}
  transform="translate({node.x}, {node.y})"
  style="--lane-color: {color}; --outline: {outline};"
>
  <!-- Pulse ring — remounts on last_update change -->
  {#key node.lastUpdate}
    <circle r={radius} class="pulse-ring" />
  {/key}

  <!-- Agreement halo -->
  {#if node.agrees && node.hasData}
    <circle r={radius + 8} class="halo" />
  {/if}

  <!-- Main disc -->
  <circle r={radius} class="disc" fill={color} />

  <!-- Icon glyph (Lucide) — consistent 22x22 bounding box via foreignObject -->
  <foreignObject
    x={-iconSize / 2}
    y={-iconSize - 4}
    width={iconSize}
    height={iconSize}
    class="icon-host"
  >
    <div xmlns="http://www.w3.org/1999/xhtml" class="icon-wrap">
      <svelte:component this={IconCmp} size={iconSize} color="rgba(0, 0, 0, 0.78)" strokeWidth={2.2} />
    </div>
  </foreignObject>

  <!-- Label inside the disc, below the icon -->
  <text y="14" text-anchor="middle" class="label">{node.label.toUpperCase()}</text>
  {#if !node.hasData}
    <text y={radius + 16} text-anchor="middle" class="no-data-tag">NO DATA</text>
  {/if}
</g>

<style>
  .lane {
    transition: transform 700ms ease;
  }
  .lane.stale {
    opacity: 0.4;
  }
  .lane.no-data {
    opacity: 0.5;
  }
  .disc {
    transition: fill 500ms ease, r 400ms ease;
    filter: drop-shadow(0 0 8px var(--lane-color));
  }
  .halo {
    fill: none;
    stroke: var(--outline);
    stroke-width: 1.2;
    stroke-opacity: 0.6;
    animation: haloBreathe 3s ease-in-out infinite;
    transform-origin: center;
    transform-box: fill-box;
  }
  @keyframes haloBreathe {
    0%, 100% { stroke-opacity: 0.5; transform: scale(1.0);  }
    50%      { stroke-opacity: 0.9; transform: scale(1.08); }
  }

  .pulse-ring {
    fill: none;
    stroke: var(--lane-color);
    stroke-width: 2;
    opacity: 0;
    transform-origin: center;
    transform-box: fill-box;
    animation: lanePulse 700ms ease-out 1;
    pointer-events: none;
  }
  @keyframes lanePulse {
    0%   { opacity: 0.9; transform: scale(0.9); }
    100% { opacity: 0;   transform: scale(1.9); }
  }

  .icon-host {
    overflow: visible;
    pointer-events: none;
  }
  .icon-wrap {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 0;
  }

  .label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 12px;
    letter-spacing: 1.8px;
    fill: rgba(0, 0, 0, 0.78);
    pointer-events: none;
  }
  .lane.no-data .label {
    fill: rgba(255, 255, 255, 0.55);
  }

  .no-data-tag {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 9px;
    letter-spacing: 1.5px;
    fill: rgba(255, 255, 255, 0.3);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.55);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
</style>
