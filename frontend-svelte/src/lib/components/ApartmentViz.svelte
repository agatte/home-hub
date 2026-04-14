<script>
  import { lights } from '$lib/stores/lights.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  /** @type {Record<string, {on: boolean, bri?: number, hue?: number, sat?: number, ct?: number, colormode?: string}> | null} */
  export let previewLightStates = null
  export let tryItActive = false

  /** Light positions in SVG coordinate space */
  const LIGHT_POSITIONS = {
    '1': { x: 90,  y: 68 },
    '2': { x: 330, y: 58 },
    '3': { x: 120, y: 140 },
    '4': { x: 210, y: 140 },
  }

  const ROOM_LABELS = [
    { x: 105, y: 32,  text: 'LIVING ROOM' },
    { x: 325, y: 32,  text: 'BEDROOM' },
    { x: 160, y: 122, text: 'KITCHEN' },
  ]

  /**
   * Get the effective state for a light — preview overrides live.
   * @param {string} id
   * @param {Record<string, any>} liveMap
   */
  function effectiveState(id, liveMap) {
    if (previewLightStates && previewLightStates[id]) {
      return previewLightStates[id]
    }
    return liveMap[id] || { on: false }
  }

  /**
   * Compute glow radius from brightness (0-254 → 25-70 SVG units).
   * @param {{ on: boolean, bri?: number }} state
   */
  function glowRadius(state) {
    if (!state?.on) return 5
    const bri = state.bri ?? 128
    return 12 + (bri / 254) * 18
  }

  /**
   * Compute glow opacity from brightness.
   * @param {{ on: boolean, bri?: number }} state
   */
  function glowOpacity(state) {
    if (!state?.on) return 0.08
    const bri = state.bri ?? 128
    return 0.25 + (bri / 254) * 0.55
  }

  $: liveMap = $lights
</script>

<div class="apartment-viz" class:previewing={previewLightStates != null}>
  <svg viewBox="0 0 420 175" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="bloom" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="8" />
      </filter>
      <filter id="bloom-soft" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="3" />
      </filter>
    </defs>

    <!-- Apartment walls -->
    <g class="walls">
      <!-- Main outer walls (living room + bedroom) -->
      <rect x="15" y="12" width="390" height="90" rx="3"
        fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="1.5" />
      <!-- Kitchen (below, left portion) -->
      <rect x="15" y="102" width="270" height="60" rx="3"
        fill="none" stroke="rgba(255,255,255,0.07)" stroke-width="1.5" />
      <!-- Room divider: living room | bedroom -->
      <line x1="210" y1="12" x2="210" y2="70"
        stroke="rgba(255,255,255,0.05)" stroke-width="1" stroke-dasharray="4 4" />
      <!-- Divider between upper rooms and kitchen -->
      <line x1="15" y1="102" x2="285" y2="102"
        stroke="rgba(255,255,255,0.05)" stroke-width="1" />
    </g>

    <!-- Room labels -->
    {#each ROOM_LABELS as room}
      <text x={room.x} y={room.y}
        class="room-label"
        text-anchor="middle"
        fill="rgba(255,255,255,0.18)"
        font-size="9"
        font-family="'Source Sans 3', sans-serif"
        font-weight="600"
        letter-spacing="1.5"
      >{room.text}</text>
    {/each}

    <!-- Light glows (bloom layer behind) -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      {@const r = glowRadius(state)}
      {@const opacity = glowOpacity(state)}
      <circle
        cx={pos.x} cy={pos.y} r={r * 1.3}
        fill={color}
        opacity={opacity * 0.35}
        filter="url(#bloom)"
        class="light-bloom"
      />
    {/each}

    <!-- Light glows (main layer) -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      {@const r = glowRadius(state)}
      {@const opacity = glowOpacity(state)}
      <circle
        cx={pos.x} cy={pos.y} r={r}
        fill={color}
        opacity={opacity}
        filter="url(#bloom-soft)"
        class="light-glow"
      />
    {/each}

    <!-- Light center dots -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      <circle
        cx={pos.x} cy={pos.y} r="4"
        fill={state?.on ? color : 'rgba(255,255,255,0.12)'}
        stroke="rgba(255,255,255,0.2)"
        stroke-width="0.5"
        class="light-dot"
      />
    {/each}

    <!-- Light ID labels -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const name = liveMap[id]?.name ?? `Light ${id}`}
      <text
        x={pos.x} y={pos.y + 20}
        text-anchor="middle"
        fill={state?.on ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.2)'}
        font-size="7.5"
        font-family="'Source Sans 3', sans-serif"
        font-weight="500"
        class="light-label"
      >{name}</text>
    {/each}

    <!-- Preview indicator -->
    {#if previewLightStates}
      <text x="400" y="168" text-anchor="end"
        fill="rgba(255,255,255,0.35)"
        font-size="8"
        font-family="'Bebas Neue', sans-serif"
        letter-spacing="2"
        class="preview-badge"
      >PREVIEW</text>
    {/if}

    {#if tryItActive}
      <text x="400" y="168" text-anchor="end"
        fill="rgba(120,220,160,0.5)"
        font-size="8"
        font-family="'Bebas Neue', sans-serif"
        letter-spacing="2"
        class="preview-badge"
      >LIVE TRY</text>
    {/if}
  </svg>
</div>

<style>
  .apartment-viz {
    width: 100%;
    max-width: 600px;
    margin: 0 auto;
    position: relative;
  }

  .apartment-viz svg {
    width: 100%;
    height: auto;
    display: block;
  }

  .light-bloom, .light-glow, .light-dot {
    transition: r 0.8s ease, fill 0.8s ease, opacity 0.8s ease;
  }

  .light-label {
    transition: fill 0.5s ease;
    pointer-events: none;
  }

  .preview-badge {
    animation: pulse-badge 1.5s ease-in-out infinite;
  }

  @keyframes pulse-badge {
    0%, 100% { opacity: 0.35; }
    50% { opacity: 0.6; }
  }

  .previewing .light-bloom, .previewing .light-glow, .previewing .light-dot {
    transition: r 0.3s ease, fill 0.3s ease, opacity 0.3s ease;
  }

  .walls rect, .walls line {
    transition: stroke 0.5s ease;
  }
</style>
