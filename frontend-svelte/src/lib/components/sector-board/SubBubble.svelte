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

  // Bubble size derives from impact — heavier sub-signals read bigger.
  $: radius = 9 + Math.max(0, Math.min(1, impact)) * 5

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
    style="--bubble-color: {color}; animation-delay: {wigglePhase}s;"
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
    /* Gentle wiggle layered on top of the parent's positioning translate. */
    animation: sub-wiggle 6s ease-in-out infinite;
  }
  .sub-bubble.stale {
    opacity: 0.5;
    animation-duration: 9s;
  }

  @keyframes sub-wiggle {
    0%, 100% { transform: translate(0, 0); }
    25%      { transform: translate(2px, -2px); }
    50%      { transform: translate(-1px, 2px); }
    75%      { transform: translate(-2px, -1px); }
  }

  .sub-display {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 11px;
    font-weight: 500;
    fill: rgba(255, 255, 255, 0.85);
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.7);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
  .sub-label {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 9px;
    fill: rgba(255, 255, 255, 0.4);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    paint-order: stroke;
    stroke: rgba(0, 0, 0, 0.7);
    stroke-width: 2.5;
    stroke-linejoin: round;
  }
</style>
