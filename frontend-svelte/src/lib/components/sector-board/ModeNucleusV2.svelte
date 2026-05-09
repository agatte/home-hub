<script>
  import { tweened } from 'svelte/motion'
  import { cubicInOut } from 'svelte/easing'
  import { modeColor, modeLabel } from '$lib/theme.js'

  /** @type {string} */
  export let mode = 'idle'
  /** @type {number} */
  export let confidence = 0
  /** @type {number} */
  export let cx
  /** @type {number} */
  export let cy
  /** @type {number} */
  export let radius = 90

  // Two-layer nucleus: an "outgoing" disc (previous mode, fading out) and
  // an "incoming" disc (new mode, fading in). When `mode` changes we swap
  // them and tween radius + opacity for ~2s.
  let outgoingMode = mode
  let incomingMode = mode
  let outgoingActive = false  // true only during a transition

  // Tweens — fresh `tweened` instances per render keeps things simple.
  // Outgoing disc shrinks from full → 0; incoming disc grows from 0 → full.
  const TRANSITION_MS = 2000
  /** @type {import('svelte/motion').Tweened<number>} */
  const outgoingScale = tweened(1, { duration: TRANSITION_MS, easing: cubicInOut })
  /** @type {import('svelte/motion').Tweened<number>} */
  const incomingScale = tweened(1, { duration: TRANSITION_MS, easing: cubicInOut })
  /** @type {import('svelte/motion').Tweened<number>} */
  const outgoingOpacity = tweened(0, { duration: TRANSITION_MS, easing: cubicInOut })
  /** @type {import('svelte/motion').Tweened<number>} */
  const incomingOpacity = tweened(1, { duration: TRANSITION_MS, easing: cubicInOut })

  /** @type {ReturnType<typeof setTimeout> | null} */
  let cleanupTimer = null

  $: handleModeChange(mode)

  function handleModeChange(newMode) {
    if (newMode === incomingMode) return
    // Stage outgoing as the previously-incoming mode, kick off the transition.
    outgoingMode = incomingMode
    incomingMode = newMode
    outgoingActive = true

    // Reset to "transition starting" state, then animate to "complete".
    outgoingScale.set(1, { duration: 0 })
    outgoingOpacity.set(1, { duration: 0 })
    incomingScale.set(0, { duration: 0 })
    incomingOpacity.set(0, { duration: 0 })

    // Animate the change.
    outgoingScale.set(0)
    outgoingOpacity.set(0)
    incomingScale.set(1)
    incomingOpacity.set(1)

    // After the animation, drop the outgoing layer.
    if (cleanupTimer) clearTimeout(cleanupTimer)
    cleanupTimer = setTimeout(() => {
      outgoingActive = false
      cleanupTimer = null
    }, TRANSITION_MS + 100)
  }

  $: outgoingFill = modeColor(outgoingMode)
  $: incomingFill = modeColor(incomingMode)
  $: incomingLabel = modeLabel(incomingMode).toUpperCase()
  $: outgoingLabel = modeLabel(outgoingMode).toUpperCase()
  $: confPct = Math.round((confidence ?? 0) * 100)
</script>

<g transform="translate({cx}, {cy})" class="nucleus">
  <!-- Breathing outer ring — independent of transition; ambient effect -->
  <circle
    r={radius + 14}
    fill="none"
    stroke={incomingFill}
    stroke-opacity="0.18"
    stroke-width="1"
    class="breathe-outer"
  />
  <circle
    r={radius + 6}
    fill="none"
    stroke={incomingFill}
    stroke-opacity="0.32"
    stroke-width="1.5"
    class="breathe-inner"
  />

  <!-- Outgoing mode (only present during a transition) -->
  {#if outgoingActive}
    <circle
      r={radius * $outgoingScale}
      fill={outgoingFill}
      fill-opacity={$outgoingOpacity}
      class="disc"
    />
  {/if}

  <!-- Incoming / current mode -->
  <circle
    r={radius * $incomingScale}
    fill={incomingFill}
    fill-opacity={$incomingOpacity}
    class="disc"
  />

  <!-- Label crossfade -->
  {#if outgoingActive}
    <text
      class="mode-label"
      text-anchor="middle"
      y="-4"
      style="opacity: {$outgoingOpacity};"
    >{outgoingLabel}</text>
  {/if}
  <text
    class="mode-label"
    text-anchor="middle"
    y="-4"
    style="opacity: {$incomingOpacity};"
  >{incomingLabel}</text>

  <!-- Confidence below label -->
  <text
    class="mode-conf"
    text-anchor="middle"
    y="16"
    style="opacity: {$incomingOpacity};"
  >{confPct}% confidence</text>
</g>

<style>
  .breathe-outer {
    transform-origin: center;
    transform-box: fill-box;
    animation: breathe 4s ease-in-out infinite;
  }
  .breathe-inner {
    transform-origin: center;
    transform-box: fill-box;
    animation: breathe 4s ease-in-out infinite reverse;
  }

  @keyframes breathe {
    0%, 100% { transform: scale(1); opacity: 1; }
    50%      { transform: scale(1.03); opacity: 0.7; }
  }

  .disc {
    filter: drop-shadow(0 0 18px var(--mode-glow, rgba(140, 100, 200, 0.55)));
  }

  .mode-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 38px;
    letter-spacing: 5px;
    fill: rgba(0, 0, 0, 0.82);
    pointer-events: none;
    paint-order: stroke;
    stroke: rgba(255, 255, 255, 0.18);
    stroke-width: 1;
    stroke-linejoin: round;
  }

  .mode-conf {
    font-family: var(--font-body, 'Source Sans 3', sans-serif);
    font-size: 11px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    fill: rgba(0, 0, 0, 0.55);
    pointer-events: none;
  }
</style>
