<script>
  /** @type {{x: number, y: number}} */
  export let from
  /** @type {{x: number, y: number}} */
  export let through
  /** @type {{x: number, y: number}} */
  export let to
  /** @type {string} */
  export let color = 'rgba(255,255,255,0.8)'

  // Polyline through the mode nucleus so the eye reads the path as
  // "input → decision → output". A quadratic Bezier with the nucleus as
  // control would feel more organic, but a polyline makes the causal
  // routing through the decision center unambiguous.
  $: pathD = `M ${from.x} ${from.y} L ${through.x} ${through.y} L ${to.x} ${to.y}`
</script>

<g class="pulse-link" style="--pulse-color: {color};">
  <!-- Faint trail line drawing the route -->
  <path d={pathD} class="pulse-trail" />

  <!-- Bright traveling dot -->
  <circle r="6" class="pulse-dot">
    <animateMotion dur="1.2s" repeatCount="1" fill="freeze" path={pathD} />
  </circle>
</g>

<style>
  .pulse-trail {
    fill: none;
    stroke: var(--pulse-color);
    stroke-width: 2.5;
    stroke-opacity: 0;
    stroke-linecap: round;
    stroke-linejoin: round;
    animation: trail-pulse 1.2s ease-out 1 forwards;
    pointer-events: none;
    filter: drop-shadow(0 0 6px var(--pulse-color));
  }
  @keyframes trail-pulse {
    0%   { stroke-opacity: 0;   }
    18%  { stroke-opacity: 0.65; }
    55%  { stroke-opacity: 0.45; }
    100% { stroke-opacity: 0;   }
  }

  .pulse-dot {
    fill: var(--pulse-color);
    opacity: 0;
    animation: dot-pulse 1.2s ease-out 1 forwards;
    filter: drop-shadow(0 0 10px var(--pulse-color));
    pointer-events: none;
  }
  @keyframes dot-pulse {
    0%   { opacity: 0; }
    10%  { opacity: 1; }
    85%  { opacity: 1; }
    100% { opacity: 0; }
  }
</style>
