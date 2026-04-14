<script>
  import { lights } from '$lib/stores/lights.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  /** @type {Record<string, {on: boolean, bri?: number, hue?: number, sat?: number, ct?: number, colormode?: string}> | null} */
  export let previewLightStates = null
  export let tryItActive = false

  /*
   * Floor plan mapped from actual apartment layout:
   *
   *   +--BEDROOM--+------LIVING------+--+
   *   |           |                  |BA|  (BA = balcony)
   *   |    *2     |              *1  |LC|
   *   |           |   (door)        |NY|
   *   +---  ------+------  ---------+--+
   *   | BATH | LD |                    |
   *   |      | WH |    KITCHEN         |
   *   +------+----+      *3    *4      |
   *   | CLOSET   |                  [P]|
   *   +-----ENTRY+--------------------+
   *
   *  Light 1: Living room lamp (near balcony, top-right)
   *  Light 2: Bedroom Lamp (bedroom, top-left)
   *  Light 3: Kitchen front (kitchen, left-center)
   *  Light 4: Kitchen back (kitchen, right-center)
   */

  /** Light positions in SVG coordinate space — matched to red dots on floor plan */
  const LIGHT_POSITIONS = {
    '2': { x: 90,  y: 72 },    // Bedroom lamp
    '1': { x: 310, y: 68 },    // Living room lamp (near balcony)
    '3': { x: 230, y: 205 },   // Kitchen front (near DW/island)
    '4': { x: 300, y: 215 },   // Kitchen back (deeper in kitchen)
  }

  const ROOM_LABELS = [
    { x: 88,  y: 35,  text: 'BEDROOM' },
    { x: 270, y: 35,  text: 'LIVING' },
    { x: 275, y: 175, text: 'KITCHEN' },
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
   * Compute glow radius from brightness.
   * @param {{ on: boolean, bri?: number }} state
   */
  function glowRadius(state) {
    if (!state?.on) return 4
    const bri = state.bri ?? 128
    return 10 + (bri / 254) * 16
  }

  /**
   * Compute glow opacity from brightness.
   * @param {{ on: boolean, bri?: number }} state
   */
  function glowOpacity(state) {
    if (!state?.on) return 0.06
    const bri = state.bri ?? 128
    return 0.3 + (bri / 254) * 0.5
  }

  $: liveMap = $lights
</script>

<div class="apartment-viz" class:previewing={previewLightStates != null}>
  <svg viewBox="0 0 400 280" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="bloom" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="6" />
      </filter>
      <filter id="bloom-soft" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" />
      </filter>
    </defs>

    <!-- ============ ROOM FILLS (subtle tints to distinguish spaces) ============ -->
    <!-- Bedroom -->
    <rect x="18" y="18" width="150" height="110" rx="2"
      fill="rgba(255,255,255,0.012)" />
    <!-- Living room -->
    <rect x="168" y="18" width="185" height="110" rx="2"
      fill="rgba(255,255,255,0.018)" />
    <!-- Balcony -->
    <rect x="338" y="5" width="45" height="30" rx="2"
      fill="rgba(140,180,255,0.02)" />
    <!-- Kitchen -->
    <rect x="168" y="150" width="215" height="108" rx="2"
      fill="rgba(255,255,255,0.012)" />
    <!-- Bath -->
    <rect x="18" y="150" width="72" height="62" rx="2"
      fill="rgba(255,255,255,0.008)" />
    <!-- Closet -->
    <rect x="18" y="228" width="72" height="30" rx="2"
      fill="rgba(255,255,255,0.006)" />

    <!-- ============ WALLS ============ -->
    <g class="walls">
      <!-- Outer walls — main apartment outline -->
      <!-- Top: bedroom + living -->
      <line x1="18" y1="18" x2="353" y2="18" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Top: balcony top -->
      <line x1="338" y1="5" x2="383" y2="5" stroke="rgba(255,255,255,0.06)" stroke-width="1" stroke-dasharray="3 2" />
      <!-- Right side: balcony -->
      <line x1="383" y1="5" x2="383" y2="35" stroke="rgba(255,255,255,0.06)" stroke-width="1" stroke-dasharray="3 2" />
      <!-- Right side: balcony to living -->
      <line x1="353" y1="18" x2="383" y2="18" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
      <!-- Right side: living room -->
      <line x1="383" y1="18" x2="383" y2="128" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Right side: kitchen -->
      <line x1="383" y1="128" x2="383" y2="258" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Bottom: kitchen + entry -->
      <line x1="168" y1="258" x2="383" y2="258" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Bottom: entry area -->
      <line x1="90" y1="258" x2="138" y2="258" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Left: closet + bath + bedroom -->
      <line x1="18" y1="258" x2="18" y2="18" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />
      <!-- Bottom-left: closet -->
      <line x1="18" y1="258" x2="90" y2="258" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />

      <!-- Interior walls -->
      <!-- Bedroom | Living divider (with door gap) -->
      <line x1="168" y1="18" x2="168" y2="88" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <line x1="168" y1="105" x2="168" y2="128" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <!-- Horizontal divider: upper rooms | lower rooms -->
      <line x1="18" y1="128" x2="90" y2="128" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <!-- Bath/Laundry wall gap (door into hallway) -->
      <line x1="105" y1="128" x2="168" y2="128" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <line x1="168" y1="128" x2="168" y2="150" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
      <!-- Kitchen top wall (opening from hallway) -->
      <line x1="168" y1="150" x2="210" y2="150" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <line x1="240" y1="150" x2="383" y2="150" stroke="rgba(255,255,255,0.08)" stroke-width="1.2" />
      <!-- Bath | Laundry divider -->
      <line x1="90" y1="128" x2="90" y2="212" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
      <!-- Closet top wall -->
      <line x1="18" y1="228" x2="90" y2="228" stroke="rgba(255,255,255,0.06)" stroke-width="1" />
      <!-- Pantry (thin strip on right of kitchen) -->
      <line x1="365" y1="220" x2="365" y2="258" stroke="rgba(255,255,255,0.04)" stroke-width="0.8" />
    </g>

    <!-- ============ FURNITURE (subtle silhouettes) ============ -->
    <g class="furniture" opacity="0.06">
      <!-- Bed (bedroom, against left wall) -->
      <rect x="24" y="48" width="52" height="68" rx="3" fill="white" />
      <!-- Bedroom desk (right side of bedroom) -->
      <rect x="130" y="46" width="30" height="14" rx="1.5" fill="white" />

      <!-- Couch (living room, center-left) -->
      <rect x="190" y="85" width="55" height="20" rx="3" fill="white" />
      <!-- TV/desk area (living room, against divider wall) -->
      <rect x="175" y="28" width="14" height="42" rx="1.5" fill="white" />

      <!-- Kitchen island/counter -->
      <rect x="240" y="195" width="50" height="22" rx="2" fill="white" />
      <!-- Kitchen counter (along right wall) -->
      <rect x="363" y="160" width="16" height="70" rx="1.5" fill="white" />
      <!-- Kitchen counter (along bottom wall) -->
      <rect x="260" y="242" width="80" height="12" rx="1.5" fill="white" />
      <!-- Stove -->
      <rect x="348" y="240" width="16" height="14" rx="1" fill="white" />

      <!-- Toilet (bath) -->
      <rect x="24" y="162" width="14" height="18" rx="4" fill="white" />
      <!-- Bathtub -->
      <rect x="50" y="155" width="32" height="16" rx="3" fill="white" />

      <!-- Washer/dryer (laundry) -->
      <rect x="100" y="165" width="20" height="18" rx="2" fill="white" />
      <rect x="100" y="190" width="20" height="18" rx="2" fill="white" />
    </g>

    <!-- ============ DOOR OPENINGS (small arcs to indicate swing) ============ -->
    <g class="doors" opacity="0.06">
      <!-- Bedroom door arc -->
      <path d="M 168 88 Q 154 96 168 105" fill="none" stroke="white" stroke-width="0.8" />
      <!-- Kitchen opening arc -->
      <path d="M 210 150 Q 225 138 240 150" fill="none" stroke="white" stroke-width="0.8" />
      <!-- Bath door arc -->
      <path d="M 90 128 Q 103 135 105 128" fill="none" stroke="white" stroke-width="0.8" />
      <!-- Entry door -->
      <path d="M 138 258 Q 150 245 168 258" fill="none" stroke="white" stroke-width="0.8" />
    </g>

    <!-- ============ ROOM LABELS ============ -->
    {#each ROOM_LABELS as room}
      <text x={room.x} y={room.y}
        class="room-label"
        text-anchor="middle"
        fill="rgba(255,255,255,0.15)"
        font-size="8"
        font-family="'Source Sans 3', sans-serif"
        font-weight="600"
        letter-spacing="1.5"
      >{room.text}</text>
    {/each}
    <!-- Smaller labels for secondary rooms -->
    <text x="54" y="168" text-anchor="middle" fill="rgba(255,255,255,0.08)"
      font-size="5.5" font-family="'Source Sans 3', sans-serif" font-weight="500" letter-spacing="1">BATH</text>
    <text x="54" y="242" text-anchor="middle" fill="rgba(255,255,255,0.08)"
      font-size="5.5" font-family="'Source Sans 3', sans-serif" font-weight="500" letter-spacing="1">CLOSET</text>
    <text x="360" y="17" text-anchor="middle" fill="rgba(255,255,255,0.07)"
      font-size="5" font-family="'Source Sans 3', sans-serif" font-weight="500" letter-spacing="0.8">BALCONY</text>

    <!-- ============ LIGHT GLOWS ============ -->

    <!-- Bloom layer (outer soft glow) -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      {@const r = glowRadius(state)}
      {@const opacity = glowOpacity(state)}
      <circle
        cx={pos.x} cy={pos.y} r={r * 1.4}
        fill={color}
        opacity={opacity * 0.3}
        filter="url(#bloom)"
        class="light-bloom"
      />
    {/each}

    <!-- Main glow layer -->
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

    <!-- Center dots -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      <circle
        cx={pos.x} cy={pos.y} r="3"
        fill={state?.on ? color : 'rgba(255,255,255,0.1)'}
        stroke="rgba(255,255,255,0.25)"
        stroke-width="0.5"
        class="light-dot"
      />
    {/each}

    <!-- Light name labels (positioned below each dot) -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const name = liveMap[id]?.name ?? `Light ${id}`}
      <text
        x={pos.x} y={pos.y + 18}
        text-anchor="middle"
        fill={state?.on ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.15)'}
        font-size="6"
        font-family="'Source Sans 3', sans-serif"
        font-weight="500"
        class="light-label"
      >{name}</text>
    {/each}

    <!-- ============ STATUS BADGES ============ -->
    {#if previewLightStates}
      <text x="390" y="272" text-anchor="end"
        fill="rgba(255,255,255,0.35)"
        font-size="7"
        font-family="'Bebas Neue', sans-serif"
        letter-spacing="2"
        class="preview-badge"
      >PREVIEW</text>
    {/if}

    {#if tryItActive}
      <text x="390" y="272" text-anchor="end"
        fill="rgba(120,220,160,0.5)"
        font-size="7"
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
    max-width: 560px;
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

  .walls line {
    transition: stroke 0.5s ease;
  }
</style>
