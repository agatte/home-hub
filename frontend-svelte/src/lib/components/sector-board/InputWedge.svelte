<script>
  import { Cpu, Video, Mic, Clock, Sun, Cloud, Music, Lightbulb } from 'lucide-svelte'
  import { modeColor, modeColorSoft } from '$lib/theme.js'
  import SubBubble from './SubBubble.svelte'
  import { subBubblePositions, sectorMidAngle } from './sectors.js'

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
  /** Whether this wedge is the agent-narrator's "today's story" input. */
  /** @type {boolean} */
  export let isHeadline = false
  /** Whether this wedge is in the agent-narrator's anomaly list. */
  /** @type {boolean} */
  export let isAnomaly = false
  /** One-line reason from the agent for the headline (only shown when isHeadline). */
  /** @type {string} */
  export let headlineReason = ''

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
  // Disc radius scales with impactScore (computed in sectorBoard.js).
  // Range 32–58 keeps even the smallest disc visually substantial (label
  // and icon both read clearly) while letting a high-impact wedge — Sonos
  // playing, weather storming, process voting at 0.45 — visibly dominate.
  const MIN_BUBBLE_R = 32
  const MAX_BUBBLE_R = 58
  $: impactScore = Math.max(0, Math.min(1, sectorData?.impactScore ?? 0.4))
  $: bubbleRadius = MIN_BUBBLE_R + (MAX_BUBBLE_R - MIN_BUBBLE_R) * impactScore
  $: IconCmp = ICON_MAP[sectorMeta?.icon] || Cpu
  // Icon scales with the disc so tiny bubbles don't have giant icons.
  $: iconSize = Math.round(bubbleRadius * 0.55)
  // Label/weight font sizes scale with the disc.
  $: labelFontSize = Math.round(10 + bubbleRadius * 0.08)
  $: weightFontSize = Math.round(9 + bubbleRadius * 0.06)
  $: labelY = Math.round(bubbleRadius * 0.3)

  $: subPositions = subBubblePositions(
    index, cx, cy, R_input, R_sub, sectorData?.factors?.length || 0,
  )

  // Outward-radial direction for the headline pill placement.
  $: outwardAngle = sectorMidAngle(index)
  $: pillDistance = bubbleRadius + 22
  $: pillX = position.x + Math.cos(outwardAngle) * pillDistance
  $: pillY = position.y + Math.sin(outwardAngle) * pillDistance

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
  class:headline={isHeadline}
  class:anomaly={isAnomaly}
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
        wigglePhase={(index * 1.7 + i * 2.3) % 11}
        wiggleCycle={9 + ((index * 3 + i * 5) % 7)}
      />
    {/if}
  {/each}

  <!-- Input bubble + label. Outer <g> handles deterministic position;
       inner <g> hosts a slow drift so the input feels alive without
       detaching from its sub-bubble cluster. -->
  <g transform="translate({position.x}, {position.y})">
    <g
      class="input-bubble"
      style="animation-delay: {(index * 1.3) % 9}s; animation-duration: {15 + (index * 2) % 6}s;"
    >
    <!-- Anomaly warning halo (drawn behind everything else) -->
    {#if isAnomaly}
      <circle r={bubbleRadius + 12} class="anomaly-halo" />
    {/if}

    <!-- Headline "today's story" gold ring -->
    {#if isHeadline}
      <circle r={bubbleRadius + 10} class="headline-ring" />
    {/if}

    <!-- Pulse ring (subtle, no key-driven remount in 2.A) -->
    <circle r={bubbleRadius + 4} class="input-halo" stroke={tint} />

    <circle r={bubbleRadius} class="input-disc" fill={tint} />

    <!-- Icon glyph centered in the upper half -->
    <foreignObject
      x={-iconSize / 2}
      y={-bubbleRadius / 2 - iconSize / 2 + 2}
      width={iconSize}
      height={iconSize}
      class="icon-host"
    >
      <div xmlns="http://www.w3.org/1999/xhtml" class="icon-wrap">
        <svelte:component this={IconCmp} size={iconSize} color="rgba(0, 0, 0, 0.78)" strokeWidth={2.2} />
      </div>
    </foreignObject>

    <!-- Label inside the disc, lower half. Font scales gently with the disc
         so a 58px wedge feels weighty and a 32px one stays readable. -->
    <text class="input-label" text-anchor="middle" y={labelY} style="font-size: {labelFontSize}px">{sectorMeta.label.toUpperCase()}</text>
    {#if weightPct !== null}
      <text class="input-weight" text-anchor="middle" y={labelY + labelFontSize + 2} style="font-size: {weightFontSize}px">{weightPct}%</text>
    {/if}

    <!-- "TODAY'S STORY" pill at outward radial direction, only on the
         narrator-flagged headline wedge. Positioned relative to the input
         bubble center so it drifts together. -->
    {#if isHeadline}
      <g class="headline-pill" transform="translate({Math.cos(outwardAngle) * pillDistance}, {Math.sin(outwardAngle) * pillDistance})">
        <rect x="-66" y="-11" width="132" height="22" rx="11" class="pill-bg" />
        <text x="0" y="4" text-anchor="middle" class="pill-text">★ TODAY'S STORY</text>
        {#if headlineReason}
          <title>{headlineReason}</title>
        {/if}
      </g>
    {/if}
    </g>
  </g>
</g>

<style>
  .wedge.stale {
    opacity: 0.55;
  }
  .wedge.no-data {
    opacity: 0.45;
  }

  .input-bubble {
    /* Slow ambient drift — small enough that the wedge label still reads
       attached to its position, large enough to feel alive. */
    animation: input-drift 17s ease-in-out infinite;
    transform-origin: center;
    transform-box: fill-box;
  }

  /* Narrator decoration: gold ring around the day's headline input. */
  .headline-ring {
    fill: none;
    stroke: rgba(255, 200, 80, 0.85);
    stroke-width: 2;
    stroke-dasharray: 4 5;
    transform-origin: center;
    transform-box: fill-box;
    animation: headline-pulse 4s ease-in-out infinite;
    filter: drop-shadow(0 0 8px rgba(255, 200, 80, 0.55));
  }
  @keyframes headline-pulse {
    0%, 100% { stroke-opacity: 0.55; transform: scale(1); }
    50%      { stroke-opacity: 0.95; transform: scale(1.04); }
  }

  /* Narrator decoration: amber warning halo for anomaly inputs. */
  .anomaly-halo {
    fill: none;
    stroke: rgba(255, 140, 80, 0.5);
    stroke-width: 1.4;
    transform-origin: center;
    transform-box: fill-box;
    animation: anomaly-pulse 3.5s ease-in-out infinite;
  }
  @keyframes anomaly-pulse {
    0%, 100% { stroke-opacity: 0.35; transform: scale(1); }
    50%      { stroke-opacity: 0.7;  transform: scale(1.12); }
  }

  /* "TODAY'S STORY" pill at outward radial direction. */
  .headline-pill {
    pointer-events: auto;
  }
  .pill-bg {
    fill: rgba(20, 20, 32, 0.85);
    stroke: rgba(255, 200, 80, 0.85);
    stroke-width: 1.4;
    filter: drop-shadow(0 0 6px rgba(255, 200, 80, 0.5));
  }
  .pill-text {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 1.6px;
    fill: rgba(255, 220, 140, 0.95);
    pointer-events: none;
  }

  @keyframes input-drift {
    0%   { transform: translate(0, 0); }
    25%  { transform: translate(4px, -3px); }
    50%  { transform: translate(-3px, -5px); }
    75%  { transform: translate(-5px, 3px); }
    100% { transform: translate(0, 0); }
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
