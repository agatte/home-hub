<script>
  import { onMount, onDestroy } from 'svelte'
  import { sectorBoard } from '$lib/stores/sectorBoard.js'
  import { SECTORS, sectorBounds, inputBubblePosition, sectorPath } from './sectors.js'
  import InputWedge from './InputWedge.svelte'
  import LightWedge from './LightWedge.svelte'
  import ModeNucleusV2 from './ModeNucleusV2.svelte'
  import OverrideBadge from './OverrideBadge.svelte'
  import SectorBoardMobile from './SectorBoardMobile.svelte'

  // Canvas sizing — bound to the host container via ResizeObserver.
  let width = 720
  let height = 580

  /** @type {HTMLElement | null} */
  let container = null
  /** @type {ResizeObserver | null} */
  let resizeObserver = null

  // Mobile fallback below this width.
  let isMobile = false
  /** @type {MediaQueryList | null} */
  let mobileMedia = null

  onMount(() => {
    if (container) {
      resizeObserver = new ResizeObserver((entries) => {
        for (const e of entries) {
          width = e.contentRect.width || width
          height = e.contentRect.height || height
        }
      })
      resizeObserver.observe(container)
    }
    mobileMedia = window.matchMedia('(max-width: 600px)')
    isMobile = mobileMedia.matches
    const mqHandler = (e) => { isMobile = e.matches }
    mobileMedia.addEventListener('change', mqHandler)
    return () => {
      mobileMedia?.removeEventListener('change', mqHandler)
    }
  })

  onDestroy(() => {
    if (resizeObserver) resizeObserver.disconnect()
  })

  // Geometry. Center near the visual middle. Radii scale with the smaller
  // dimension so the whole board resizes responsively.
  $: minDim = Math.min(width, height)
  $: cx = width / 2
  $: cy = height / 2
  $: nucleusRadius = Math.max(70, Math.round(minDim * 0.13))
  // Input bubbles sit between the nucleus and the canvas edge. Capped so a
  // wide kiosk doesn't push them so far out that sub-bubbles fall off-screen.
  $: R_INPUT = Math.max(150, Math.min(210, Math.round(minDim * 0.26)))
  // Sub-bubbles sit beyond the input bubble's outer edge with enough slack
  // for the max input radius (58) + max sub radius (22) + drift wiggle.
  $: R_SUB = R_INPUT + 110
  // Inner / outer wedge edge radii — used for boundary rendering only.
  $: rInner = nucleusRadius + 18
  $: rOuter = Math.round(minDim * 0.46)

  // Pre-compute per-sector positions so children can reuse.
  $: sectorPositions = SECTORS.map((s, i) => ({
    meta: s,
    index: i,
    pos: inputBubblePosition(i, cx, cy, R_INPUT),
    bounds: sectorBounds(i),
  }))
</script>

<div bind:this={container} class="board-host">
  {#if isMobile}
    <SectorBoardMobile />
  {:else}
    <svg
      class="board-svg"
      viewBox="0 0 {width} {height}"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Live decision pipeline — mode and inputs"
    >
      <!-- Faint sector boundary glyphs — hairlines only, just enough to suggest the wedge. -->
      <g class="sector-boundaries">
        {#each SECTORS as _s, i}
          <path
            d={sectorPath(i, cx, cy, rInner, rOuter)}
            class="sector-fill"
          />
        {/each}
      </g>

      <!-- Each sector's content. Lights wedge gets its own component because
           its sub-bubbles are bulb states, not factor pips. -->
      {#each sectorPositions as sp (sp.meta.id)}
        {#if sp.meta.id === 'lights'}
          <LightWedge
            sectorMeta={sp.meta}
            sectorData={$sectorBoard.sectors.lights}
            index={sp.index}
            {cx}
            {cy}
            R_input={R_INPUT}
            R_sub={R_SUB}
            position={sp.pos}
          />
        {:else}
          <InputWedge
            sectorMeta={sp.meta}
            sectorData={$sectorBoard.sectors[sp.meta.id]}
            index={sp.index}
            fusedMode={$sectorBoard.mode.current}
            {cx}
            {cy}
            R_input={R_INPUT}
            R_sub={R_SUB}
            position={sp.pos}
          />
        {/if}
      {/each}

      <!-- Override / DND badge above the nucleus -->
      <OverrideBadge
        active={$sectorBoard.mode.override}
        dnd={$sectorBoard.mode.dnd}
        source={$sectorBoard.mode.source}
        {cx}
        {cy}
        yOffset={nucleusRadius + 38}
      />

      <!-- The mode nucleus sits on top so it can transform across other elements. -->
      <ModeNucleusV2
        mode={$sectorBoard.mode.current}
        confidence={$sectorBoard.mode.confidence}
        {cx}
        {cy}
        radius={nucleusRadius}
      />
    </svg>
  {/if}
</div>

<style>
  .board-host {
    position: relative;
    width: 100%;
    /* Slightly taller than wide so sectors near 12 and 6 o'clock have
       enough vertical room for their sub-bubble fan-outs. Capped so the
       layout doesn't run away on a 1280-wide kiosk. */
    aspect-ratio: 1 / 1.05;
    min-height: 600px;
    max-height: 820px;
    margin: 0 auto;
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md, 14px);
    backdrop-filter: blur(10px);
    overflow: hidden;
  }

  .board-svg {
    width: 100%;
    height: 100%;
    display: block;
  }

  /* Sector boundary fill — almost invisible. The wedges read as soft regions
     because the eye groups by clustering, not because we draw lines. A faint
     fill gradient gives just enough hint of structure. */
  .sector-fill {
    fill: rgba(255, 255, 255, 0.012);
    stroke: rgba(255, 255, 255, 0.04);
    stroke-width: 0.5;
  }
</style>
