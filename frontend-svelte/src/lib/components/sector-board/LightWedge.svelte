<script>
  import { Lightbulb } from 'lucide-svelte'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'
  import { subBubblePositions } from './sectors.js'

  /** @type {{id: string, label: string, icon: string, kind: string}} */
  export let sectorMeta
  /** @type {{lights: Array<{light_id:string,name:string,on:boolean,bri:number,hue:number,sat:number,ct?:number,colormode?:string,reachable:boolean}>}} */
  export let sectorData
  /** @type {number} */
  export let index
  /** @type {number} */
  export let cx
  /** @type {number} */
  export let cy
  /** @type {number} */
  export let R_input
  /** @type {number} */
  export let R_sub
  /** @type {{x: number, y: number}} */
  export let position

  $: lights = sectorData?.lights || []
  $: bubbleRadius = 40

  // Position each light bubble within the sector wedge.
  $: lightPositions = subBubblePositions(index, cx, cy, R_input, R_sub, lights.length)
</script>

<g class="wedge light-wedge">
  <!-- Each light as a colored bubble within the wedge -->
  {#each lights as light, i (light.light_id)}
    {#if lightPositions[i]}
      <g transform="translate({lightPositions[i].x}, {lightPositions[i].y})" class="light-cell" class:light-off={!light.on} class:light-unreachable={!light.reachable}>
        {#key `${light.bri}-${light.hue}-${light.sat}-${light.on}`}
          <circle r="11" class="light-pulse" style="--light-color: {lightStateToCSS(light)};" />
        {/key}
        <circle
          r="14"
          fill={lightStateToCSS(light)}
          class="light-bulb"
        />
        <text class="light-name" text-anchor="middle" y="28">{light.name}</text>
      </g>
    {/if}
  {/each}

  <!-- Input bubble (the wedge label) — same shape as InputWedge for consistency -->
  <g transform="translate({position.x}, {position.y})" class="input-bubble">
    <circle r={bubbleRadius + 4} class="input-halo" />
    <circle r={bubbleRadius} class="input-disc" />

    <foreignObject x={-12} y={-bubbleRadius / 2 - 4} width="24" height="24" class="icon-host">
      <div xmlns="http://www.w3.org/1999/xhtml" class="icon-wrap">
        <Lightbulb size={22} color="rgba(0, 0, 0, 0.78)" strokeWidth={2.2} />
      </div>
    </foreignObject>

    <text class="input-label" text-anchor="middle" y="14">{sectorMeta.label.toUpperCase()}</text>
    <text class="input-sub" text-anchor="middle" y="26">{lights.length} fixtures</text>
  </g>
</g>

<style>
  .input-disc {
    fill: rgba(255, 220, 130, 0.55);
    filter: drop-shadow(0 0 12px rgba(255, 220, 130, 0.4));
  }
  .input-halo {
    fill: none;
    stroke: rgba(255, 220, 130, 0.45);
    stroke-width: 1.4;
    transform-origin: center;
    transform-box: fill-box;
    animation: light-halo 6s ease-in-out infinite;
  }
  @keyframes light-halo {
    0%, 100% { transform: scale(1.0); stroke-opacity: 0.4; }
    50%      { transform: scale(1.06); stroke-opacity: 0.75; }
  }

  .icon-host { overflow: visible; pointer-events: none; }
  .icon-wrap {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 0;
  }

  .input-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 1.6px;
    fill: rgba(0, 0, 0, 0.78);
    pointer-events: none;
  }
  .input-sub {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 9px;
    fill: rgba(0, 0, 0, 0.55);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    pointer-events: none;
  }

  .light-bulb {
    transition: fill 600ms ease, r 300ms ease;
    stroke: rgba(255, 255, 255, 0.18);
    stroke-width: 1;
    filter: drop-shadow(0 0 10px currentColor);
  }
  .light-cell.light-off .light-bulb {
    opacity: 0.55;
    filter: none;
  }
  .light-cell.light-unreachable .light-bulb {
    stroke: rgba(255, 100, 100, 0.55);
    stroke-dasharray: 3 3;
  }
  .light-name {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 10px;
    fill: rgba(255, 255, 255, 0.72);
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.7);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }

  /* Pulse ring — re-mounts via {#key} on every state change, runs once. */
  .light-pulse {
    fill: none;
    stroke: var(--light-color, rgba(255, 220, 130, 0.8));
    stroke-width: 2;
    opacity: 0;
    transform-origin: center;
    transform-box: fill-box;
    animation: light-pulse 700ms ease-out 1;
    pointer-events: none;
  }
  @keyframes light-pulse {
    0%   { opacity: 0.85; transform: scale(0.85); }
    100% { opacity: 0;    transform: scale(2.4); }
  }
</style>
