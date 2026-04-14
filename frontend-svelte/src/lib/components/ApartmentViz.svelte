<script>
  import { lights } from '$lib/stores/lights.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  /** @type {Record<string, {on: boolean, bri?: number, hue?: number, sat?: number, ct?: number, colormode?: string}> | null} */
  export let previewLightStates = null
  export let tryItActive = false

  /*
   * Apartment layout (from Anthony's drawing):
   *
   *   +----------+------------------+
   *   |          |               *1 |
   *   | BEDROOM  |   LIVING ROOM    |
   *   |          |                  |
   *   |    *2    |                  |
   *   +----+-----+------+---------+
   *   |    |             |         |
   *   |BATH|   KITCHEN   |         |
   *   |    |    *3       |         |
   *   |    |    *4       |         |
   *   +----+-------------+---------+
   *
   *  Light 1: Living room lamp (top-right corner)
   *  Light 2: Bedroom Lamp (bottom-center of bedroom)
   *  Light 3: Kitchen front (above island)
   *  Light 4: Kitchen back (below island)
   */

  const LIGHT_POSITIONS = {
    '2': { x: 88,  y: 105 },   // Bedroom lamp — bottom-center of bedroom
    '1': { x: 335, y: 42 },    // Living room lamp — top-right area (inset from wall)
    '3': { x: 195, y: 195 },   // Kitchen front — left of island
    '4': { x: 280, y: 195 },   // Kitchen back — right of island
  }

  const ROOM_LABELS = [
    { x: 88,  y: 42,  text: 'BEDROOM' },
    { x: 272, y: 42,  text: 'LIVING ROOM' },
    { x: 230, y: 162, text: 'KITCHEN' },
  ]

  function effectiveState(id, liveMap) {
    if (previewLightStates && previewLightStates[id]) {
      return previewLightStates[id]
    }
    return liveMap[id] || { on: false }
  }

  function glowRadius(state) {
    if (!state?.on) return 4
    const bri = state.bri ?? 128
    // sqrt scaling flattens the curve — high bri doesn't balloon
    const t = Math.sqrt(bri / 254)
    return 10 + t * 12
  }

  function glowOpacity(state) {
    if (!state?.on) return 0.06
    const bri = state.bri ?? 128
    const t = Math.sqrt(bri / 254)
    return 0.3 + t * 0.45
  }

  $: liveMap = $lights
</script>

<div class="apartment-viz" class:previewing={previewLightStates != null}>
  <svg viewBox="0 0 400 270" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="bloom" x="-100%" y="-100%" width="300%" height="300%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="6" />
      </filter>
      <filter id="bloom-soft" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur in="SourceGraphic" stdDeviation="2.5" />
      </filter>
    </defs>

    <!-- ============ ROOM FILLS ============ -->
    <rect x="16" y="16" width="148" height="118" rx="2"
      fill="rgba(255,255,255,0.015)" />
    <rect x="164" y="16" width="220" height="118" rx="2"
      fill="rgba(255,255,255,0.02)" />
    <rect x="16" y="134" width="76" height="118" rx="2"
      fill="rgba(255,255,255,0.008)" />
    <rect x="92" y="134" width="292" height="118" rx="2"
      fill="rgba(255,255,255,0.015)" />

    <!-- ============ WALLS ============ -->
    <g class="walls">
      <!-- Outer rectangle -->
      <rect x="16" y="16" width="368" height="236" rx="3"
        fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="1.5" />

      <!-- Vertical divider: bedroom | living room (with door gap) -->
      <line x1="164" y1="16" x2="164" y2="100"
        stroke="rgba(255,255,255,0.09)" stroke-width="1.2" />
      <line x1="164" y1="118" x2="164" y2="134"
        stroke="rgba(255,255,255,0.09)" stroke-width="1.2" />

      <!-- Horizontal divider: top rooms | bottom rooms -->
      <line x1="16" y1="134" x2="92" y2="134"
        stroke="rgba(255,255,255,0.09)" stroke-width="1.2" />
      <line x1="92" y1="134" x2="384" y2="134"
        stroke="rgba(255,255,255,0.09)" stroke-width="1.2" />

      <!-- Bath | Kitchen divider -->
      <line x1="92" y1="134" x2="92" y2="220"
        stroke="rgba(255,255,255,0.07)" stroke-width="1" />
      <line x1="92" y1="238" x2="92" y2="252"
        stroke="rgba(255,255,255,0.07)" stroke-width="1" />
    </g>

    <!-- ============ DOOR ARCS ============ -->
    <g class="doors" opacity="0.05">
      <!-- Bedroom door (gap in bedroom/living divider) -->
      <path d="M 164 100 Q 150 109 164 118" fill="none" stroke="white" stroke-width="0.8" />
      <!-- Bath door (gap in bath/kitchen divider) -->
      <path d="M 92 220 Q 80 229 92 238" fill="none" stroke="white" stroke-width="0.8" />
    </g>

    <!-- ============ FURNITURE ============ -->
    <g class="furniture" opacity="0.05">
      <!-- Bed (bedroom, left wall) -->
      <rect x="22" y="50" width="48" height="65" rx="3" fill="white" />
      <!-- Nightstand -->
      <rect x="22" y="40" width="16" height="10" rx="1" fill="white" />

      <!-- Couch (living room, bottom-left area) -->
      <rect x="180" y="100" width="56" height="18" rx="3" fill="white" />
      <!-- TV stand (living room, right wall) -->
      <rect x="362" y="50" width="14" height="40" rx="1.5" fill="white" />

      <!-- Kitchen island (centered between lights 3 & 4) -->
      <rect x="226" y="186" width="26" height="20" rx="2" fill="white" />
      <!-- Counter (right wall) -->
      <rect x="360" y="142" width="18" height="65" rx="1.5" fill="white" />
      <!-- Counter (bottom wall) -->
      <rect x="180" y="238" width="110" height="10" rx="1.5" fill="white" />

      <!-- Toilet -->
      <rect x="24" y="180" width="12" height="16" rx="4" fill="white" />
      <!-- Tub/shower -->
      <rect x="44" y="142" width="36" height="18" rx="2" fill="white" />
    </g>

    <!-- ============ ROOM LABELS ============ -->
    {#each ROOM_LABELS as room}
      <text x={room.x} y={room.y}
        text-anchor="middle"
        fill="rgba(255,255,255,0.14)"
        font-size="8"
        font-family="'Source Sans 3', sans-serif"
        font-weight="600"
        letter-spacing="1.5"
      >{room.text}</text>
    {/each}
    <text x="54" y="162" text-anchor="middle" fill="rgba(255,255,255,0.07)"
      font-size="6" font-family="'Source Sans 3', sans-serif" font-weight="500" letter-spacing="1">BATH</text>

    <!-- ============ LIGHT GLOWS ============ -->

    <!-- Bloom layer -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const color = lightStateToCSS(state)}
      {@const r = glowRadius(state)}
      {@const opacity = glowOpacity(state)}
      <circle
        cx={pos.x} cy={pos.y} r={r * 1.2}
        fill={color}
        opacity={opacity * 0.25}
        filter="url(#bloom)"
        class="light-bloom"
      />
    {/each}

    <!-- Main glow -->
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

    <!-- Light name labels -->
    {#each Object.entries(LIGHT_POSITIONS) as [id, pos]}
      {@const state = effectiveState(id, liveMap)}
      {@const name = liveMap[id]?.name ?? `Light ${id}`}
      <text
        x={pos.x} y={pos.y + 17}
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
      <text x="378" y="260" text-anchor="end"
        fill="rgba(255,255,255,0.35)"
        font-size="7"
        font-family="'Bebas Neue', sans-serif"
        letter-spacing="2"
        class="preview-badge"
      >PREVIEW</text>
    {/if}

    {#if tryItActive}
      <text x="378" y="260" text-anchor="end"
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

  .walls line, .walls rect {
    transition: stroke 0.5s ease;
  }
</style>
