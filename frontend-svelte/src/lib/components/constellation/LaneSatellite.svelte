<script>
  import { modeColor, modeColorSoft } from '$lib/theme.js'

  /** @type {{ x: number, y: number, lane: string, label: string, mode: string | null, weight: number, agrees: boolean, stale: boolean, hasData: boolean, confidence: number, lastUpdate: string | null, icon: string }} */
  export let node
  /** @type {string} */
  export let fusedMode = 'idle'

  $: laneMode = node?.mode || 'idle'
  $: color = node?.hasData ? modeColor(laneMode) : 'rgba(255,255,255,0.25)'
  $: outline = node?.agrees ? modeColor(fusedMode) : modeColorSoft(laneMode, 0.55)
  $: radius = node?.stale ? 22 : 30
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
    <circle r={radius + 6} class="halo" />
  {/if}

  <!-- Main disc -->
  <circle r={radius} class="disc" fill={color} />

  <!-- Icon glyph — simple line art via SVG inline, matching PipelineInputCard -->
  <g class="icon" stroke="rgba(0,0,0,0.75)" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" transform="translate(-8, -14)">
    {#if node.icon === 'cpu'}
      <rect width="16" height="16" x="0" y="0" rx="2" />
      <rect width="6" height="6" x="5" y="5" rx="1" />
    {:else if node.icon === 'video'}
      <rect width="12" height="10" x="0" y="3" rx="1.5" />
      <path d="M12 6l4 -2v8l-4 -2z" />
    {:else if node.icon === 'mic'}
      <rect width="6" height="10" x="5" y="0" rx="3" />
      <path d="M2 8v2a6 6 0 0 0 12 0v-2" />
      <line x1="8" x2="8" y1="16" y2="18" />
    {:else if node.icon === 'brain'}
      <path d="M8 1a6 6 0 0 1 6 6c0 2.4 -2.3 4 -3.3 5.3l-0.7 1.3h-4l-0.7 -1.3C4.3 11 2 9.4 2 7a6 6 0 0 1 6 -6z" />
    {:else if node.icon === 'clock'}
      <circle cx="8" cy="8" r="7" />
      <path d="M8 4v4l3 1" />
    {/if}
  </g>

  <!-- Label below -->
  <text y={radius + 14} text-anchor="middle" class="label">{node.label.toUpperCase()}</text>
  {#if node.hasData}
    <text y={radius + 26} text-anchor="middle" class="sublabel">{node.mode}</text>
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
    font-size: 10px;
    letter-spacing: 1.5px;
    fill: rgba(255, 255, 255, 0.65);
    pointer-events: none;
  }
  .sublabel {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 10px;
    fill: rgba(255, 255, 255, 0.4);
    pointer-events: none;
    text-transform: capitalize;
  }
</style>
