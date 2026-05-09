<script>
  /** @type {boolean} */
  export let active = false
  /** @type {boolean} */
  export let dnd = false
  /** @type {string} */
  export let source = ''
  /** @type {number} */
  export let cx
  /** @type {number} */
  export let cy
  /** Distance above the nucleus center to anchor the badge. */
  /** @type {number} */
  export let yOffset = 124

  $: label = (() => {
    if (dnd && active) return 'OVERRIDE · DND'
    if (dnd) return 'DO NOT DISTURB'
    if (active) return 'MANUAL OVERRIDE'
    return ''
  })()

  // Source displays for color-coded chip — manual override differs from
  // calendar / api / rule-suggest sources visually.
  $: chipKind = (() => {
    if (dnd) return 'dnd'
    if (!active) return 'none'
    if (source === 'manual') return 'manual'
    if (source && source.startsWith('api')) return 'api'
    if (source && source.startsWith('alexa')) return 'voice'
    return 'manual'
  })()
</script>

{#if active || dnd}
  <g
    class="override-badge"
    class:kind-manual={chipKind === 'manual'}
    class:kind-dnd={chipKind === 'dnd'}
    class:kind-api={chipKind === 'api'}
    class:kind-voice={chipKind === 'voice'}
    transform="translate({cx}, {cy - yOffset})"
  >
    <rect
      x={-(label.length * 4 + 14)}
      y={-13}
      width={label.length * 8 + 28}
      height="26"
      rx="13"
      class="chip"
    />
    <text class="chip-text" text-anchor="middle" y="4">{label}</text>
  </g>
{/if}

<style>
  .override-badge {
    pointer-events: none;
  }
  .chip {
    stroke-width: 1;
    transition: fill 300ms ease;
  }
  .kind-manual .chip { fill: rgba(255, 180, 80, 0.18); stroke: rgba(255, 180, 80, 0.7); }
  .kind-dnd    .chip { fill: rgba(120, 160, 255, 0.18); stroke: rgba(120, 160, 255, 0.7); }
  .kind-api    .chip { fill: rgba(180, 140, 220, 0.18); stroke: rgba(180, 140, 220, 0.7); }
  .kind-voice  .chip { fill: rgba(140, 220, 200, 0.18); stroke: rgba(140, 220, 200, 0.7); }
  .chip-text {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 2px;
    fill: rgba(255, 255, 255, 0.85);
    text-transform: uppercase;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.55);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .kind-manual .chip-text { fill: rgba(255, 200, 130, 0.95); }
  .kind-dnd    .chip-text { fill: rgba(170, 200, 255, 0.95); }
  .kind-api    .chip-text { fill: rgba(220, 190, 250, 0.95); }
  .kind-voice  .chip-text { fill: rgba(180, 240, 220, 0.95); }
</style>
