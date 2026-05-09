<script>
  /** @type {number} */
  export let x
  /** @type {number} */
  export let y
  /** @type {string} */
  export let label = ''
  /** @type {string} */
  export let display = ''
  /** @type {number} */
  export let impact = 0.5
  /** @type {boolean} */
  export let stale = false
  /** @type {string} */
  export let color = 'rgba(255,255,255,0.55)'
  /** Per-bubble wiggle phase so siblings don't move in lockstep. */
  /** @type {number} */
  export let wigglePhase = 0
  /** Per-bubble cycle duration jitter (in seconds) so siblings don't share period. */
  /** @type {number} */
  export let wiggleCycle = 11

  // Bubble size derives from impact — heavier sub-signals read bigger.
  // Min 14px so the small dots are still legible; max 22px so a heavy
  // sub-signal (vscode foreground at impact=1.0) reads as substantial
  // without crowding sibling pips.
  $: radius = 14 + Math.max(0, Math.min(1, impact)) * 8

  $: fillAlpha = stale ? 0.15 : 0.4 + impact * 0.4
</script>

<!--
  Outer <g> handles deterministic positioning via the SVG transform attribute.
  Inner <g> handles the CSS-driven wiggle as a small offset on top.
  This nesting avoids attribute-vs-CSS transform composition ambiguity.
-->
<g transform="translate({x}, {y})">
  <g
    class="sub-bubble"
    class:stale
    style="--bubble-color: {color}; animation-delay: {wigglePhase}s; animation-duration: {wiggleCycle}s;"
  >
    <circle
      r={radius}
      fill="var(--bubble-color)"
      fill-opacity={fillAlpha}
      stroke="var(--bubble-color)"
      stroke-opacity={stale ? 0.3 : 0.7}
      stroke-width="1"
    />
    <!-- The display value, e.g. "vscode" or "Afternoon" -->
    <text
      y={radius + 13}
      text-anchor="middle"
      class="sub-display"
    >{display}</text>
    {#if label && label.toLowerCase() !== (display || '').toLowerCase()}
      <text
        y={radius + 23}
        text-anchor="middle"
        class="sub-label"
      >{label}</text>
    {/if}
  </g>
</g>

<style>
  .sub-bubble {
    /* Wandering drift layered on top of the parent's positioning translate.
       5-keypoint orbital path with subtle scale breath for life. */
    animation: sub-wiggle 11s ease-in-out infinite;
    transform-origin: center;
    transform-box: fill-box;
  }
  .sub-bubble.stale {
    opacity: 0.5;
  }

  @keyframes sub-wiggle {
    0%   { transform: translate(0, 0) scale(1.00); }
    20%  { transform: translate(9px, -7px) scale(1.04); }
    40%  { transform: translate(-5px, -11px) scale(0.97); }
    60%  { transform: translate(-10px, 5px) scale(1.03); }
    80%  { transform: translate(6px, 9px) scale(0.98); }
    100% { transform: translate(0, 0) scale(1.00); }
  }

  .sub-display {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 12px;
    font-weight: 500;
    fill: rgba(255, 255, 255, 0.92);
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.8);
    stroke-width: 3;
    stroke-linejoin: round;
  }
  .sub-label {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 10px;
    fill: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.8);
    stroke-width: 3;
    stroke-linejoin: round;
  }
</style>
