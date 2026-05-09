<script>
  import { Cpu, Video, Mic, Clock, Sun, Cloud, Music, Lightbulb } from 'lucide-svelte'
  import { modeColor, modeColorSoft } from '$lib/theme.js'
  import SubBubble from './SubBubble.svelte'
  import { subBubblePositions } from './sectors.js'

  /** Shape from sectorBoard.js — see voterSector / contextSector etc. */
  /** @type {{id: string, label: string, icon: string, kind: string}} */
  export let sectorMeta
  /** @type {{id: string, kind: string, hasData: boolean, mode: string|null, weight: number, agrees: boolean, stale: boolean, factors: Array<{key:string,label:string,display:string,impact:number,stale:boolean}>}} */
  export let sectorData
  /** sector index (0..7) */
  /** @type {number} */
  export let index
  /** @type {string} */
  export let fusedMode
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

  const ICON_MAP = {
    cpu: Cpu, video: Video, mic: Mic, clock: Clock,
    sun: Sun, cloud: Cloud, music: Music, lightbulb: Lightbulb,
  }

  // Color logic:
  //   Voter sectors → tinted by their voted mode (so a voter agreeing with the
  //     fused mode visually reads as part of the chorus, while a dissenter is
  //     a different color).
  //   Context sectors → muted neutral (no opinion on mode).
  //   Stale or no-data → washed out.
  $: laneMode = sectorData?.mode || fusedMode
  $: tint = (() => {
    if (!sectorData?.hasData) return 'rgba(255,255,255,0.22)'
    if (sectorMeta?.kind === 'voter') return modeColor(laneMode)
    return modeColorSoft(fusedMode, 0.45) // context bubbles tint with the current mode for visual cohesion
  })()
  $: bubbleRadius = sectorData?.stale ? 32 : 40
  $: IconCmp = ICON_MAP[sectorMeta?.icon] || Cpu

  $: subPositions = subBubblePositions(
    index, cx, cy, R_input, R_sub, sectorData?.factors?.length || 0,
  )

  // Weight readout (voters only, when actively voting).
  $: weightPct = sectorMeta?.kind === 'voter' && sectorData?.hasData && !sectorData?.stale
    ? Math.round((sectorData.weight ?? 0) * 100)
    : null
</script>

<g
  class="wedge"
  class:stale={sectorData?.stale}
  class:no-data={!sectorData?.hasData}
  class:voter={sectorMeta?.kind === 'voter'}
  class:context={sectorMeta?.kind === 'context'}
  class:agrees={sectorData?.agrees}
>
  <!-- Sub-bubbles drawn first so the input bubble overlaps them -->
  {#each (sectorData?.factors || []) as factor, i (factor.key)}
    {#if subPositions[i]}
      <SubBubble
        x={subPositions[i].x}
        y={subPositions[i].y}
        label={factor.label}
        display={factor.display}
        impact={factor.impact}
        stale={factor.stale}
        color={tint}
        wigglePhase={(index * 0.7 + i * 0.4) % 6}
      />
    {/if}
  {/each}

  <!-- Input bubble + label -->
  <g transform="translate({position.x}, {position.y})" class="input-bubble">
    <!-- Pulse ring (subtle, no key-driven remount in 2.A) -->
    <circle r={bubbleRadius + 4} class="input-halo" stroke={tint} />

    <circle r={bubbleRadius} class="input-disc" fill={tint} />

    <!-- Icon glyph centered in the upper half -->
    <foreignObject
      x={-12}
      y={-bubbleRadius / 2 - 4}
      width="24"
      height="24"
      class="icon-host"
    >
      <div xmlns="http://www.w3.org/1999/xhtml" class="icon-wrap">
        <svelte:component this={IconCmp} size={22} color="rgba(0, 0, 0, 0.78)" strokeWidth={2.2} />
      </div>
    </foreignObject>

    <!-- Label inside the disc, lower half -->
    <text class="input-label" text-anchor="middle" y="14">{sectorMeta.label.toUpperCase()}</text>
    {#if weightPct !== null}
      <text class="input-weight" text-anchor="middle" y="26">{weightPct}%</text>
    {/if}
  </g>
</g>

<style>
  .wedge.stale {
    opacity: 0.55;
  }
  .wedge.no-data {
    opacity: 0.45;
  }

  .input-disc {
    transition: fill 600ms ease, r 400ms ease;
    filter: drop-shadow(0 0 10px currentColor);
  }
  .input-halo {
    fill: none;
    stroke-width: 1.2;
    stroke-opacity: 0.4;
    transform-origin: center;
    transform-box: fill-box;
    animation: halo-breathe 5s ease-in-out infinite;
  }
  .wedge.agrees .input-halo {
    stroke-opacity: 0.85;
    stroke-width: 1.6;
  }

  @keyframes halo-breathe {
    0%, 100% { transform: scale(1.0); stroke-opacity: 0.4; }
    50%      { transform: scale(1.08); stroke-opacity: 0.7; }
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

  .input-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 1.6px;
    fill: rgba(0, 0, 0, 0.78);
    pointer-events: none;
  }
  .wedge.no-data .input-label {
    fill: rgba(255, 255, 255, 0.55);
  }
  .input-weight {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 10px;
    letter-spacing: 0.6px;
    fill: rgba(0, 0, 0, 0.55);
    pointer-events: none;
  }
</style>
