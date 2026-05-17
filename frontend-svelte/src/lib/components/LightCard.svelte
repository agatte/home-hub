<script>
  import { setLight } from '$lib/stores/init.js'
  import { hueToHsl, ctToColor } from '$lib/utils/lightColor.js'

  import { LIGHT_CT_PRESETS } from '$lib/theme.js'

  /** @type {{ light_id: string, name: string, on: boolean, bri: number, hue: number, sat: number, ct?: number, colormode?: string, reachable: boolean }} */
  export let light

  /** Additional light ids that should mirror every command sent from this
   *  card. Used to fuse the kitchen pair (L3+L4) into a single Kitchen card —
   *  the grid renders L3 with linkedIds=['4'] and hides the L4 card. The
   *  primary light's state drives the displayed values; commands fan out to
   *  the primary plus every linked id. Empty by default. */
  /** @type {string[]} */
  export let linkedIds = []

  /** Optional display-name override. When the card represents a fused pair
   *  (e.g. Kitchen front + Kitchen back), the primary's "Kitchen front"
   *  reads weird; pass nameOverride="Kitchen" instead. */
  /** @type {string | undefined} */
  export let nameOverride = undefined

  /** @param {string} id @param {Record<string, unknown>} state */
  function fanout(id, state) {
    setLight(id, state)
    for (const linked of linkedIds) setLight(linked, state)
  }

  const COLOR_PRESETS = [
    { name: 'Warm',     hue: 8000,  sat: 140 },
    { name: 'Cool',     hue: 34000, sat: 50 },
    { name: 'Daylight', hue: 41000, sat: 30 },
    { name: 'Blue',     hue: 46920, sat: 254 },
    { name: 'Red',      hue: 0,     sat: 254 },
    { name: 'Green',    hue: 25500, sat: 254 },
    { name: 'Purple',   hue: 50000, sat: 254 },
  ]

  let presetTab = 'color' // 'color' | 'temp'
  let showPresets = false

  // Leading + trailing throttle: cap mid-drag updates to one per THROTTLE_MS.
  // Flush on drag end so the final value always lands even if it arrived
  // mid-throttle-window. Mid-drag commands ride a short transitiontime
  // (~100ms) so the bridge follows the slider tightly without a long fade —
  // without that, each new command interrupts the previous 0.4s transition
  // mid-flight and the bulb visibly bounces between targets. The flush call
  // deliberately omits transitiontime so the final landing gets phue2's
  // default 0.4s smooth fade.
  const THROTTLE_MS = 250
  const MID_DRAG_TRANSITION = 1  // 100ms — snappy mid-drag follow
  /** @type {ReturnType<typeof setTimeout> | null} */
  let throttleTimer = null
  /** @type {Record<string, unknown> | null} */
  let pendingState = null
  let lastSentAt = 0

  /** @param {Record<string, unknown>} state */
  function throttledUpdate(state) {
    const now = Date.now()
    const elapsed = now - lastSentAt
    const payload = { ...state, transitiontime: MID_DRAG_TRANSITION }
    if (elapsed >= THROTTLE_MS) {
      lastSentAt = now
      pendingState = null
      if (throttleTimer) { clearTimeout(throttleTimer); throttleTimer = null }
      fanout(light.light_id, payload)
    } else {
      pendingState = payload
      if (!throttleTimer) {
        throttleTimer = setTimeout(() => {
          throttleTimer = null
          if (pendingState) {
            lastSentAt = Date.now()
            const s = pendingState
            pendingState = null
            fanout(light.light_id, s)
          }
        }, THROTTLE_MS - elapsed)
      }
    }
  }

  /** Flush any pending update on drag end so the bulb lands on the
   *  finger-up value. No transitiontime here — phue2's 0.4s default
   *  gives a smooth landing. */
  function flushBrightness(bri) {
    if (throttleTimer) { clearTimeout(throttleTimer); throttleTimer = null }
    pendingState = null
    lastSentAt = Date.now()
    fanout(light.light_id, { bri })
  }

  function togglePower() { fanout(light.light_id, { on: !light.on }) }
  function setColor(hue, sat) {
    fanout(light.light_id, { hue, sat })
    showPresets = false
  }
  function setCT(ct) {
    fanout(light.light_id, { ct })
    showPresets = false
  }

  // ---- Pointer-driven brightness drag ----------------------------------
  //
  // The card body IS the slider. pointerdown captures the pointer, every
  // move past a 4px threshold maps clientX onto bri (1..254), and release
  // flushes the final value. Power pill + color swatch stop propagation so
  // they never seed a drag. While dragging, `displayBri` overrides
  // `light.bri` so the fill follows the finger before the WS echo lands.

  /** @type {HTMLDivElement | undefined} */
  let cardEl
  let dragging = false
  /** @type {number | null} */
  let activePointerId = null
  let dragStartX = 0
  let didDrag = false
  /** @type {number | null} */
  let pendingBri = null
  /** @type {number | null} */
  let optimisticBri = null
  const DRAG_THRESHOLD_PX = 4

  /** @param {number} clientX */
  function clampedBriFromX(clientX) {
    if (!cardEl) return light.bri
    const rect = cardEl.getBoundingClientRect()
    if (rect.width <= 0) return light.bri
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    // Hue v1 rejects bri=0; floor at 1. Range 1..254 spans the full bar.
    return Math.max(1, Math.min(254, Math.round(pct * 253) + 1))
  }

  /** @param {PointerEvent} e */
  function onPointerDown(e) {
    if (!light.reachable) return
    if (!cardEl) return
    // Touch / pen: stop the page from scrolling while we drag.
    if (e.pointerType !== 'mouse') e.preventDefault()
    cardEl.setPointerCapture(e.pointerId)
    activePointerId = e.pointerId
    dragging = true
    didDrag = false
    dragStartX = e.clientX
    pendingBri = clampedBriFromX(e.clientX)
    optimisticBri = pendingBri
  }

  /** @param {PointerEvent} e */
  function onPointerMove(e) {
    if (!dragging || e.pointerId !== activePointerId) return
    if (!didDrag && Math.abs(e.clientX - dragStartX) < DRAG_THRESHOLD_PX) return
    didDrag = true
    const bri = clampedBriFromX(e.clientX)
    pendingBri = bri
    optimisticBri = bri
    if (!light.on) {
      // Drag-to-power-on: first move past threshold while off turns the
      // light on at the dragged-to brightness. setLight's optimistic patch
      // updates the store immediately so subsequent moves see light.on=true.
      fanout(light.light_id, { on: true, bri, transitiontime: MID_DRAG_TRANSITION })
      lastSentAt = Date.now()
    } else {
      throttledUpdate({ bri })
    }
  }

  /** @param {PointerEvent} e */
  function onPointerEnd(e) {
    if (!dragging || e.pointerId !== activePointerId) return
    try { cardEl?.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
    const finalBri = pendingBri
    const wasDrag = didDrag
    dragging = false
    activePointerId = null
    didDrag = false
    pendingBri = null
    if (wasDrag && finalBri != null) {
      flushBrightness(finalBri)
    }
    // Clear optimistic after a tick so the store update has time to land.
    setTimeout(() => { optimisticBri = null }, 50)
  }

  /** @param {KeyboardEvent} e */
  function onKeydown(e) {
    if (!light.reachable) return
    let delta = 0
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') delta = 13      // ~5%
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') delta = -13
    else if (e.key === 'Home') { setBri(1); return }
    else if (e.key === 'End') { setBri(254); return }
    else if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); togglePower(); return }
    else return
    e.preventDefault()
    const target = Math.max(1, Math.min(254, (light.bri ?? 1) + delta))
    setBri(target)
  }

  /** @param {number} bri */
  function setBri(bri) {
    optimisticBri = bri
    if (!light.on) {
      fanout(light.light_id, { on: true, bri })
    } else {
      fanout(light.light_id, { bri })
    }
    setTimeout(() => { optimisticBri = null }, 100)
  }

  // ---- Derived display values ------------------------------------------
  // While dragging, use optimisticBri so the fill follows the finger.
  // Otherwise, mirror the store. `displayOn` is true if the light is on OR
  // we're actively dragging an off card up (preview the upcoming state).
  $: displayBri = optimisticBri ?? light.bri ?? 1
  $: displayOn = light.on || (dragging && didDrag)
  $: fillPct = displayOn ? Math.round((displayBri / 254) * 100) : 0
  $: pctLabel = fillPct + '%'

  /** Fill gradient color = actual bulb color. HSB mode uses the real hue/sat
   *  (with a sat floor so muted CT-mode lights don't fade into the background);
   *  CT mode reuses the ctToColor amber→cool ramp. */
  $: fillColor = (() => {
    if (!displayOn) return 'transparent'
    if (light.colormode === 'ct' && light.ct) return ctToColor(light.ct)
    if (light.hue != null && light.sat != null) {
      const h = (light.hue / 65535) * 360
      const s = Math.max(28, (light.sat / 254) * 100)
      return `hsl(${h}, ${s}%, 42%)`
    }
    return 'rgba(140, 140, 150, 0.55)'
  })()

  /** Swatch color preview (the color-picker affordance dot). */
  $: swatchColor = light.on
    ? hueToHsl(light.hue, light.sat, Math.max(light.bri, 140))
    : 'var(--text-muted)'
</script>

<!--
  The card is a composite widget: a drag-to-dim surface PLUS two embedded
  buttons (color-swatch, power). ARIA forbids interactive descendants
  inside a `role="slider"` element, so the OUTER container is `role="group"`
  and the drag surface keeps its slider semantics via aria-* attributes
  alone — Pointer/keyboard handlers stay on the outer for full-card hit
  area, but axe sees `role="group"` and accepts the nested buttons.

  Keyboard model: the group itself takes focus (Tab); Arrow / Home / End
  on the focused group adjust brightness; Space / Enter toggle power.
  A second Tab moves focus into the group, landing on the swatch button,
  then a third Tab lands on the power button — both have their own
  aria-label and run independent of the group's keydown handler.

  The brightness percentage announced to screen readers comes from the
  visible `.chip-pct` text and the composite aria-label below, not from
  a slider valuetext.
-->
<div
  class="light-chip"
  class:light-on={displayOn}
  class:light-off={!displayOn}
  class:light-unreachable={!light.reachable}
  class:dragging
  style="--fill-pct: {fillPct}%; --fill-color: {fillColor};"
  bind:this={cardEl}
  on:pointerdown={onPointerDown}
  on:pointermove={onPointerMove}
  on:pointerup={onPointerEnd}
  on:pointercancel={onPointerEnd}
  on:keydown={onKeydown}
  role="group"
  aria-label="{nameOverride ?? light.name} ({light.on ? `${pctLabel} brightness` : 'off'})"
  aria-disabled={!light.reachable}
  tabindex={light.reachable ? 0 : -1}
>
  <div class="chip-fill" aria-hidden="true"></div>

  <div class="chip-content">
    <button
      class="chip-swatch"
      style="background: {swatchColor}"
      on:pointerdown|stopPropagation
      on:click|stopPropagation={() => { if (light.on) showPresets = !showPresets }}
      aria-label="Change color"
      tabindex={light.on ? 0 : -1}
    ></button>

    <div class="chip-meta">
      <span class="chip-name">{nameOverride ?? light.name}</span>
      <span class="chip-pct">{displayOn ? pctLabel : 'Off'}</span>
    </div>

    <button
      class="chip-power"
      class:power-on={light.on}
      on:pointerdown|stopPropagation
      on:click|stopPropagation={togglePower}
      aria-label={light.on ? 'Turn off' : 'Turn on'}
    >
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2v6M18.36 6.64A9 9 0 1 1 5.64 6.64" stroke-linecap="round" />
      </svg>
    </button>
  </div>

  {#if !light.reachable}
    <span class="chip-unreachable">Offline</span>
  {/if}

  {#if showPresets && light.on}
    <div class="chip-presets">
      <div class="preset-tabs">
        <button class="preset-tab" class:active={presetTab === 'color'} on:click|stopPropagation={() => presetTab = 'color'}>Color</button>
        <button class="preset-tab" class:active={presetTab === 'temp'} on:click|stopPropagation={() => presetTab = 'temp'}>Temp</button>
      </div>
      <div class="preset-dots">
        {#if presetTab === 'color'}
          {#each COLOR_PRESETS as preset}
            {@const active = light.colormode === 'hs' && Math.abs(light.hue - preset.hue) < 2000 && Math.abs(light.sat - preset.sat) < 50}
            <button
              class="chip-preset-dot"
              class:preset-active={active}
              style="background: {hueToHsl(preset.hue, preset.sat, 200)}"
              on:pointerdown|stopPropagation
              on:click|stopPropagation={() => setColor(preset.hue, preset.sat)}
              title={preset.name}
            ></button>
          {/each}
        {:else}
          {#each LIGHT_CT_PRESETS as preset}
            {@const active = light.colormode === 'ct' && light.ct && Math.abs(light.ct - preset.ct) < 20}
            <button
              class="chip-preset-dot"
              class:preset-active={active}
              style="background: {ctToColor(preset.ct)}"
              on:pointerdown|stopPropagation
              on:click|stopPropagation={() => setCT(preset.ct)}
              title="{preset.name} ({preset.label})"
            ></button>
          {/each}
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .light-chip {
    position: relative;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 14px 14px;
    min-height: 64px;
    cursor: ew-resize;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
    transition: border-color 0.2s, background 0.2s;
  }

  .light-chip:hover {
    background: rgba(255, 255, 255, 0.045);
  }

  .light-chip.light-on {
    border-color: rgba(255, 255, 255, 0.12);
  }

  .light-chip.light-off {
    cursor: pointer;
  }

  .light-chip.light-unreachable {
    cursor: not-allowed;
    opacity: 0.55;
    filter: saturate(0.5);
  }

  .light-chip:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.4);
    outline-offset: 2px;
  }

  /* Fill is the slider — width = brightness %, gradient fades from the
     bulb's actual color at left to transparent at right. While dragging
     the transition is short so the fill tracks the finger; at rest the
     width settles smoothly when the WS echo arrives. */
  .chip-fill {
    position: absolute;
    inset: 0;
    width: var(--fill-pct, 0%);
    background: linear-gradient(
      to right,
      var(--fill-color, transparent) 0%,
      var(--fill-color, transparent) 35%,
      transparent 100%
    );
    pointer-events: none;
    transition: width 0.2s ease, background 0.3s;
  }
  .light-chip.dragging .chip-fill {
    transition: width 0.06s linear;
  }

  .chip-content {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 12px;
    height: 100%;
  }

  .chip-swatch {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1.5px solid rgba(255, 255, 255, 0.5);
    padding: 0;
    cursor: pointer;
    flex-shrink: 0;
    transition: transform 0.15s, border-color 0.15s;
    background-clip: padding-box;
  }
  .chip-swatch:hover { transform: scale(1.2); border-color: rgba(255, 255, 255, 0.85); }
  .light-off .chip-swatch { border-color: rgba(255, 255, 255, 0.18); cursor: default; }

  .chip-meta {
    display: flex;
    flex-direction: column;
    gap: 1px;
    flex: 1;
    min-width: 0;
  }

  .chip-name {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
  }

  .light-off .chip-name { color: var(--text-muted); }

  .chip-pct {
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 400;
    color: rgba(245, 243, 238, 0.55);
    letter-spacing: 0.02em;
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
  }
  .light-off .chip-pct { color: var(--text-muted); }

  .chip-power {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s, background 0.15s;
    flex-shrink: 0;
  }
  .chip-power:hover { background: rgba(255, 255, 255, 0.08); }
  .chip-power.power-on { color: var(--success); }

  .chip-unreachable {
    font-size: 10px;
    color: var(--danger);
    position: absolute;
    right: 12px;
    top: 4px;
    z-index: 2;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .chip-presets {
    position: absolute;
    left: 12px;
    top: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 10px;
    background: rgba(10, 10, 15, 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    z-index: 20;
    animation: presetsIn 0.15s ease-out;
    margin-top: 6px;
  }

  .preset-tabs { display: flex; gap: 4px; }

  .preset-tab {
    padding: 2px 8px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 10px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    cursor: pointer;
    transition: color 0.15s, background 0.15s;
  }
  .preset-tab.active {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.08);
  }

  .preset-dots { display: flex; gap: 6px; }

  @keyframes presetsIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .chip-preset-dot {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid transparent;
    cursor: pointer;
    transition: border-color 0.15s, transform 0.1s;
    padding: 0;
  }
  .chip-preset-dot:hover { transform: scale(1.15); }
  .chip-preset-dot.preset-active { border-color: var(--text-primary); }

  @media (max-width: 768px) {
    .light-chip { padding: 12px; min-height: 60px; }
    .chip-name { font-size: 13px; }
  }

  @media (max-width: 480px) {
    .light-chip { padding: 10px 12px; gap: 8px; min-height: 56px; }
    .chip-name { font-size: 12px; }
    .chip-pct { font-size: 11px; }
    .chip-power { width: 28px; height: 28px; }
  }
</style>
