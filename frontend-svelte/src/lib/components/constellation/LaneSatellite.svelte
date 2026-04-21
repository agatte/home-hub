<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, lane: string, label: string, mode: string | null, weight: number, agrees: boolean, stale: boolean, hasData: boolean, confidence: number, lastUpdate: string | null, icon: string }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  $: laneMode = node?.mode || 'idle'
  $: color = node?.hasData ? modeColor(laneMode) : 'rgba(255,255,255,0.25)'
  $: outline = node?.agrees ? modeColor(fusedMode) : modeColorSoft(laneMode, 0.55)
  $: radius = node?.stale ? 34 : 46
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

  <!-- Icon glyph — simple line art via SVG inline, matching PipelineInputCard -->
  <g class="icon" stroke="rgba(0,0,0,0.78)" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" transform="translate(-11, -20)">
    {#if node.icon === 'cpu'}
      <rect width="22" height="22" x="0" y="0" rx="3" />
      <rect width="8" height="8" x="7" y="7" rx="1.5" />
    {:else if node.icon === 'video'}
      <rect width="16" height="14" x="0" y="4" rx="2" />
      <path d="M16 8l6 -3v12l-6 -3z" />
    {:else if node.icon === 'mic'}
      <rect width="8" height="14" x="7" y="0" rx="4" />
      <path d="M3 11v2a8 8 0 0 0 16 0v-2" />
      <line x1="11" x2="11" y1="22" y2="24" />
    {:else if node.icon === 'brain'}
      <path d="M11 1a8 8 0 0 1 8 8c0 3 -3 5 -4 7l-1 2h-6l-1 -2c-1 -2 -4 -4 -4 -7a8 8 0 0 1 8 -8z" />
    {:else if node.icon === 'clock'}
      <circle cx="11" cy="11" r="9.5" />
      <path d="M11 5v6l4 2" />
    {/if}
  </g>

  <!-- Label below -->
  <text y={radius + 18} text-anchor="middle" class="label">{node.label.toUpperCase()}</text>
  {#if node.hasData}
    <text y={radius + 34} text-anchor="middle" class="sublabel">{node.mode}</text>
  {:else}
    <text y={radius + 34} text-anchor="middle" class="sublabel muted">no data</text>
  {/if}
</g>

<style>
  .lane {
    transition: transform 700ms ease;
  }
  .lane.stale {
    opacity: 0.35;
  }
  .lane.no-data {
    opacity: 0.45;
  }
  .disc {
    transition: fill 500ms ease, r 400ms ease;
    filter: drop-shadow(0 0 6px var(--lane-color));
  }
  .halo {
    fill: none;
    stroke: var(--outline);
    stroke-width: 1;
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

  .label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 2px;
    fill: rgba(255, 255, 255, 0.8);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.6);
    stroke-width: 3;
    stroke-linejoin: round;
  }
  .sublabel {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 12px;
    fill: rgba(255, 255, 255, 0.55);
    pointer-events: none;
    text-transform: capitalize;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.55);
    stroke-width: 3;
    stroke-linejoin: round;
  }
  .sublabel.muted {
    fill: rgba(255, 255, 255, 0.25);
  }
</style>
