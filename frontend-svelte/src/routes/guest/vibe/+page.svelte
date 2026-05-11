<script>
  import { onDestroy, onMount } from 'svelte'
  import { browser } from '$app/environment'
  import {
    Sparkles, Gamepad2, Monitor, Tv, PartyPopper, Flame, ChefHat, Moon, Bot,
    Music2, Pause, Play, SkipForward, Volume2, VolumeX, Home as HomeIcon,
    Sliders, Mic,
  } from 'lucide-svelte'
  import { lights } from '$lib/stores/lights.js'
  import { sonos } from '$lib/stores/sonos.js'
  import { automation } from '$lib/stores/automation.js'
  import { modeLabel, modeColor } from '$lib/theme.js'
  import { lightStateToCSS } from '$lib/utils/lightColor.js'

  // Map automation modes to Lucide components. modeLucide() returns icon
  // names as strings, but lucide-svelte needs the actual component, so we
  // do the mapping here. Falls back to Sparkles for any unknown mode.
  const MODE_ICONS = {
    gaming: Gamepad2, working: Monitor, watching: Tv, social: PartyPopper,
    relax: Flame, cooking: ChefHat, sleeping: Moon, idle: Sparkles, auto: Bot,
  }
  $: modeIcon = MODE_ICONS[$automation.mode] ?? Sparkles

  // Stable order matching the apartment's L1..L5 layout.
  $: orderedLights = ['1', '2', '5', '3', '4'].map((id) => $lights[id]).filter(Boolean)

  /** @type {Array<{name: string, display_name: string, lights: Record<string, any>}>} */
  let scenes = []
  let scenesLoaded = false

  /** @type {Array<{name: string, label: string, playlist_title: string}>} */
  let vibes = []
  let vibesLoaded = false

  // Lights and music are independent visitor controls — separate cooldowns
  // so a guest can shift the music right after picking a scene without
  // waiting for the unrelated control to release.
  /** @type {string | null} */
  let activatingScene = null
  /** @type {boolean} */
  let sceneCooldownActive = false
  /** @type {ReturnType<typeof setTimeout> | null} */
  let sceneCooldownTimer = null

  /** @type {string | null} */
  let activatingVibe = null
  /** @type {boolean} */
  let vibeCooldownActive = false
  /** @type {ReturnType<typeof setTimeout> | null} */
  let vibeCooldownTimer = null

  /** @type {string | null} */
  let toastMessage = null
  /** @type {ReturnType<typeof setTimeout> | null} */
  let toastTimer = null

  // Music transport guardrails. Era at 30 is genuinely loud in this
  // apartment; floor 5 because sub-5 is functionally muted and defeats
  // the affordance. Throttle prevents 20-PUT spam from a hammered +/-.
  const VOL_FLOOR = 5
  const VOL_CEILING = 30
  const VOL_STEP = 2
  const VOL_THROTTLE_MS = 400

  let transportBusy = false
  let volBusy = false
  let lastVolAt = 0
  let handbackBusy = false

  // Wave 2 — in-scene tuning. Persisted in sessionStorage so a phone-lock
  // + reload during the same browser session doesn't dump the guest back
  // to "no scene active". Cleared on hand-back (override → false).
  const TUNE_STATE_KEY = 'guest-vibe-tuning-v1'
  const BRIGHTNESS_LEVEL_CAP = 3
  const BRIGHTNESS_THROTTLE_MS = 800

  /** @type {string | null} */
  let activeScene = null
  /** @type {'candle' | 'sparkle' | null} */
  let activeEffectOverlay = null
  let kitchenDropped = false
  let brightnessLevel = 0

  let tuningBusy = false
  let lastBrightnessAt = 0

  // Toast TTS — guest types a short message, system speaks it through the
  // Sonos. Server enforces a 60s global cooldown; we mirror it client-side
  // so the button shows a live countdown instead of a delayed 429 toast.
  const TOAST_MAX_CHARS = 120
  const TOAST_NAME_MAX_CHARS = 30
  let toastInput = ''
  let toastNameInput = ''
  let toastSending = false
  /** Epoch ms when the cooldown ends. 0 = no active cooldown. */
  let toastCooldownUntil = 0
  /** Reactive "now" for the cooldown countdown — bumped every second. */
  let toastNow = Date.now()
  /** @type {ReturnType<typeof setInterval> | null} */
  let toastTicker = null
  $: toastCooldownRemaining = Math.max(0, Math.ceil((toastCooldownUntil - toastNow) / 1000))

  $: isPlaying = $sonos.state === 'PLAYING'

  // Drop tuning state when the override goes away (hand-back, host kiosk
  // override-clear, or 4h timeout). Survives reload otherwise.
  $: if (browser && !$automation.manual_override && activeScene !== null) {
    activeScene = null
    activeEffectOverlay = null
    kitchenDropped = false
    brightnessLevel = 0
    sessionStorage.removeItem(TUNE_STATE_KEY)
  }

  function persistTuningState() {
    if (!browser) return
    sessionStorage.setItem(TUNE_STATE_KEY, JSON.stringify({
      activeScene, activeEffectOverlay, kitchenDropped, brightnessLevel,
    }))
  }

  function loadTuningState() {
    if (!browser) return
    try {
      const raw = sessionStorage.getItem(TUNE_STATE_KEY)
      if (!raw) return
      const s = JSON.parse(raw)
      activeScene = s.activeScene ?? null
      activeEffectOverlay = s.activeEffectOverlay ?? null
      kitchenDropped = s.kitchenDropped ?? false
      brightnessLevel = s.brightnessLevel ?? 0
    } catch {
      /* malformed payload — ignore */
    }
  }

  function showToast(msg) {
    toastMessage = msg
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toastMessage = null }, 3000)
  }

  function startSceneCooldown(seconds) {
    sceneCooldownActive = true
    if (sceneCooldownTimer) clearTimeout(sceneCooldownTimer)
    sceneCooldownTimer = setTimeout(() => { sceneCooldownActive = false }, seconds * 1000)
  }

  function startVibeCooldown(seconds) {
    vibeCooldownActive = true
    if (vibeCooldownTimer) clearTimeout(vibeCooldownTimer)
    vibeCooldownTimer = setTimeout(() => { vibeCooldownActive = false }, seconds * 1000)
  }

  async function activateScene(name) {
    if (sceneCooldownActive || activatingScene) return
    activatingScene = name
    try {
      const res = await fetch(`/api/guest/scene/${name}`, { method: 'POST' })
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}))
        const retryAfter = parseInt(res.headers.get('Retry-After') ?? '15', 10) || 15
        startSceneCooldown(retryAfter)
        showToast(body.detail || `Cooling down — try again in ${retryAfter}s`)
        return
      }
      if (!res.ok) {
        showToast(`Couldn't change the lights (${res.status})`)
        return
      }
      const body = await res.json()
      startSceneCooldown(body.cooldown_seconds ?? 15)
      const sceneLabel = body.scene || name
      showToast(`Lights set to ${sceneLabel}`)
      // Activating a fresh scene resets all tuning — guest's previous
      // tweaks shouldn't carry over to a different palette.
      activeScene = name
      activeEffectOverlay = null
      kitchenDropped = false
      brightnessLevel = 0
      persistTuningState()
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      activatingScene = null
    }
  }

  async function activateVibe(name) {
    if (vibeCooldownActive || activatingVibe) return
    activatingVibe = name
    try {
      const res = await fetch(`/api/guest/vibe/${name}`, { method: 'POST' })
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}))
        const retryAfter = parseInt(res.headers.get('Retry-After') ?? '15', 10) || 15
        startVibeCooldown(retryAfter)
        showToast(body.detail || `Cooling down — try again in ${retryAfter}s`)
        return
      }
      if (res.status === 502) {
        showToast(`That playlist isn't on the speaker right now`)
        return
      }
      if (!res.ok) {
        showToast(`Couldn't switch the music (${res.status})`)
        return
      }
      const body = await res.json()
      startVibeCooldown(body.cooldown_seconds ?? 15)
      showToast(`Now playing: ${body.playlist || body.vibe || name}`)
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      activatingVibe = null
    }
  }

  async function postSonos(path) {
    if (transportBusy) return
    transportBusy = true
    try {
      const res = await fetch(path, { method: 'POST' })
      if (!res.ok) showToast(`Couldn't reach the speaker (${res.status})`)
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      transportBusy = false
    }
  }

  const togglePlayPause = () =>
    postSonos(isPlaying ? '/api/sonos/pause' : '/api/sonos/play')

  const skipNext = () => postSonos('/api/sonos/next')

  async function bumpVolume(delta) {
    const now = Date.now()
    if (now - lastVolAt < VOL_THROTTLE_MS) return
    lastVolAt = now
    const current = $sonos.volume ?? 10
    const next = Math.max(VOL_FLOOR, Math.min(VOL_CEILING, current + delta))
    if (next === current) return
    volBusy = true
    try {
      await fetch('/api/sonos/volume', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ volume: next }),
      })
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      volBusy = false
    }
  }

  // Brightness drag — visitor pulls the fill toward "dimmer" (left) or
  // "brighter" (right). Fill width = level mapped onto a 0..100% axis
  // (50% = level 0, 0% = -3, 100% = +3). The level system is unchanged;
  // we just swapped the +/- rocker for a single card-fill drag so it
  // visually rhymes with the home-dashboard light cards.
  //
  // While dragging, `dragLevel` overrides `brightnessLevel` so the fill
  // tracks the finger. On release we compute `target - current` and post
  // it as a single batch step — server applies the whole delta in one shot
  // (avoids chaining 6× 800ms-throttled up/down calls for a full swing).

  /** @type {HTMLDivElement | undefined} */
  let brightnessCardEl
  let brightnessDragging = false
  /** @type {number | null} */
  let brightnessDragPointerId = null
  /** @type {number | null} */
  let dragLevel = null
  let brightnessDragStartX = 0
  let brightnessDidDrag = false

  $: displayBrightnessLevel = dragLevel ?? brightnessLevel
  $: brightnessFillPct = ((displayBrightnessLevel + BRIGHTNESS_LEVEL_CAP) / (BRIGHTNESS_LEVEL_CAP * 2)) * 100

  function levelFromClientX(clientX) {
    if (!brightnessCardEl) return brightnessLevel
    const rect = brightnessCardEl.getBoundingClientRect()
    if (rect.width <= 0) return brightnessLevel
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    const raw = pct * (BRIGHTNESS_LEVEL_CAP * 2) - BRIGHTNESS_LEVEL_CAP
    return Math.max(-BRIGHTNESS_LEVEL_CAP, Math.min(BRIGHTNESS_LEVEL_CAP, Math.round(raw)))
  }

  /** @param {PointerEvent} e */
  function onBrightnessPointerDown(e) {
    if (tuningBusy || !activeScene) return
    if (!brightnessCardEl) return
    if (e.pointerType !== 'mouse') e.preventDefault()
    brightnessCardEl.setPointerCapture(e.pointerId)
    brightnessDragPointerId = e.pointerId
    brightnessDragging = true
    brightnessDidDrag = false
    brightnessDragStartX = e.clientX
    dragLevel = levelFromClientX(e.clientX)
  }

  /** @param {PointerEvent} e */
  function onBrightnessPointerMove(e) {
    if (!brightnessDragging || e.pointerId !== brightnessDragPointerId) return
    if (!brightnessDidDrag && Math.abs(e.clientX - brightnessDragStartX) < 4) return
    brightnessDidDrag = true
    dragLevel = levelFromClientX(e.clientX)
  }

  /** @param {PointerEvent} e */
  async function onBrightnessPointerEnd(e) {
    if (!brightnessDragging || e.pointerId !== brightnessDragPointerId) return
    try { brightnessCardEl?.releasePointerCapture(e.pointerId) } catch { /* ignore */ }
    const target = dragLevel
    const wasDrag = brightnessDidDrag
    brightnessDragging = false
    brightnessDragPointerId = null
    brightnessDidDrag = false
    if (!wasDrag || target == null || target === brightnessLevel) {
      dragLevel = null
      return
    }
    await commitBrightnessLevel(target)
    dragLevel = null
  }

  async function commitBrightnessLevel(target) {
    if (tuningBusy) return
    const delta = target - brightnessLevel
    if (delta === 0) return
    const now = Date.now()
    if (now - lastBrightnessAt < BRIGHTNESS_THROTTLE_MS) {
      showToast('Slow down a sec')
      return
    }
    lastBrightnessAt = now
    tuningBusy = true
    try {
      const res = await fetch(`/api/guest/brightness/step/${delta}`, { method: 'POST' })
      if (res.status === 429) {
        showToast('Slow down a sec')
        return
      }
      if (!res.ok) {
        showToast(`Couldn't adjust brightness (${res.status})`)
        return
      }
      const body = await res.json().catch(() => ({}))
      if (Array.isArray(body.updated) && body.updated.length === 0) {
        showToast(delta > 0 ? 'Already at max' : 'Already at min')
        return
      }
      brightnessLevel = target
      persistTuningState()
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      tuningBusy = false
    }
  }

  async function toggleKitchen() {
    if (tuningBusy || !activeScene) return
    tuningBusy = true
    try {
      if (kitchenDropped) {
        // Restore the kitchen pair from the active scene's preset baseline.
        // We re-PUT the original L3/L4 states (not just `on:true`) so colors
        // / brightness match the rest of the palette, not whatever the bridge
        // remembered before "off".
        const preset = scenes.find((s) => s.name === activeScene)
        for (const id of ['3', '4']) {
          const ls = preset?.lights?.[id]
          if (!ls) continue
          await fetch(`/api/lights/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ls),
          })
        }
        kitchenDropped = false
      } else {
        for (const id of ['3', '4']) {
          await fetch(`/api/lights/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ on: false }),
          })
        }
        kitchenDropped = true
      }
      persistTuningState()
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      tuningBusy = false
    }
  }

  async function toggleEffect(name) {
    if (tuningBusy) return
    tuningBusy = true
    try {
      // Mutual exclusivity: tap the active chip → stop. Tap a different chip
      // → that effect replaces the previous one (Hue v2 only runs one effect
      // at a time anyway).
      const target = activeEffectOverlay === name ? 'stop' : name
      const res = await fetch(`/api/guest/effect/${target}`, { method: 'POST' })
      if (res.status === 429) {
        showToast('Effect cooling down')
        return
      }
      if (!res.ok) {
        showToast(`Couldn't change effect (${res.status})`)
        return
      }
      activeEffectOverlay = target === 'stop' ? null : name
      persistTuningState()
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      tuningBusy = false
    }
  }

  async function resetScene() {
    if (tuningBusy || !activeScene) return
    tuningBusy = true
    try {
      const res = await fetch(`/api/guest/scene/${activeScene}/reset`, { method: 'POST' })
      if (!res.ok) {
        showToast(`Couldn't reset (${res.status})`)
        return
      }
      activeEffectOverlay = null
      kitchenDropped = false
      brightnessLevel = 0
      persistTuningState()
      showToast('Scene reset to baseline')
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      tuningBusy = false
    }
  }

  function startToastCooldown(seconds) {
    toastCooldownUntil = Date.now() + seconds * 1000
    if (!toastTicker) {
      toastTicker = setInterval(() => {
        toastNow = Date.now()
        if (toastNow >= toastCooldownUntil && toastTicker) {
          clearInterval(toastTicker)
          toastTicker = null
        }
      }, 1000)
    }
  }

  async function sendToast() {
    if (toastSending || toastCooldownRemaining > 0) return
    const message = toastInput.trim()
    if (!message) return
    const name = toastNameInput.trim()
    toastSending = true
    try {
      const res = await fetch('/api/guest/toast', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, name: name || null }),
      })
      if (res.status === 429) {
        const retryAfter = parseInt(res.headers.get('Retry-After') ?? '60', 10) || 60
        startToastCooldown(retryAfter)
        showToast(`Hold on — try again in ${retryAfter}s`)
        return
      }
      if (!res.ok) {
        showToast(`Couldn't send the toast (${res.status})`)
        return
      }
      const body = await res.json()
      startToastCooldown(body.cooldown_seconds ?? 60)
      toastInput = ''
      toastNameInput = ''
      showToast('Toast sent — listen up 🥂')
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      toastSending = false
    }
  }

  async function handBack() {
    if (handbackBusy) return
    handbackBusy = true
    try {
      const res = await fetch('/api/guest/handback', { method: 'POST' })
      if (!res.ok) {
        showToast(`Couldn't hand back (${res.status})`)
        return
      }
      showToast('Returned to host autopilot')
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      handbackBusy = false
    }
  }

  onMount(async () => {
    // Restore any in-flight tuning state from before the page reloaded.
    loadTuningState()
    // Fetch scenes + vibes in parallel — both are read-only GETs and
    // can race independently.
    const [sceneRes, vibeRes] = await Promise.allSettled([
      fetch('/api/guest/scenes').then((r) => r.ok ? r.json() : null).catch(() => null),
      fetch('/api/guest/vibes').then((r) => r.ok ? r.json() : null).catch(() => null),
    ])
    if (sceneRes.status === 'fulfilled' && sceneRes.value) {
      scenes = sceneRes.value.scenes ?? []
    }
    scenesLoaded = true
    if (vibeRes.status === 'fulfilled' && vibeRes.value) {
      vibes = vibeRes.value.vibes ?? []
    }
    vibesLoaded = true
  })

  onDestroy(() => {
    if (toastTimer) clearTimeout(toastTimer)
    if (sceneCooldownTimer) clearTimeout(sceneCooldownTimer)
    if (vibeCooldownTimer) clearTimeout(vibeCooldownTimer)
    if (toastTicker) clearInterval(toastTicker)
  })
</script>

<svelte:head>
  <title>Vibe — Home Hub</title>
</svelte:head>

<main class="guest-page">
  {#if $automation.manual_override}
    <button
      type="button"
      class="handback-btn"
      on:click={handBack}
      disabled={handbackBusy}
    >
      <HomeIcon size={16} strokeWidth={1.6} />
      <span>Hand it back to the host</span>
    </button>
  {/if}

  <header class="guest-header">
    <h1>Vibe</h1>
    <p class="guest-subtitle">What the room is doing</p>
  </header>

  <section class="guest-card">
    <div class="card-head">
      <svelte:component
        this={modeIcon}
        size={20}
        strokeWidth={1.5}
        color={modeColor($automation.mode)}
      />
      <h2>Right now</h2>
    </div>
    <div class="mode-line">
      <span class="mode-name">{modeLabel($automation.mode)}</span>
      {#if $automation.manual_override}
        {#if $automation.source === 'guest'}
          <span class="src-chip src-chip-guest">🏠 Set by a guest</span>
        {:else}
          <span class="src-chip src-chip-manual">Manual override</span>
        {/if}
      {/if}
    </div>
    <div class="swatch-row">
      {#each orderedLights as light}
        <div
          class="swatch-dot"
          class:swatch-off={!light.on}
          style="background: {lightStateToCSS(light)}"
          title={light.name}
        ></div>
      {/each}
    </div>
    {#if $sonos.state === 'PLAYING' && ($sonos.track || $sonos.artist)}
      <div class="now-playing">
        {#if $sonos.art_url}
          <img class="np-art" src={$sonos.art_url} alt="Album artwork" />
        {/if}
        <div class="np-text">
          <div class="np-title">{$sonos.track || '—'}</div>
          {#if $sonos.artist}
            <div class="np-artist">{$sonos.artist}</div>
          {/if}
        </div>
      </div>
    {:else}
      <p class="np-empty">Speaker is quiet.</p>
    {/if}
  </section>

  <section class="guest-card">
    <div class="card-head">
      <Music2 size={20} strokeWidth={1.5} />
      <h2>Music controls</h2>
    </div>
    <div class="transport-row">
      <button
        type="button"
        class="transport-btn"
        on:click={togglePlayPause}
        disabled={transportBusy}
        aria-label={isPlaying ? 'Pause' : 'Play'}
      >
        <svelte:component this={isPlaying ? Pause : Play} size={22} strokeWidth={1.6} />
      </button>
      <button
        type="button"
        class="transport-btn"
        on:click={skipNext}
        disabled={transportBusy}
        aria-label="Skip"
      >
        <SkipForward size={22} strokeWidth={1.6} />
      </button>
      <div class="volume-rocker">
        <button
          type="button"
          class="vol-btn"
          on:click={() => bumpVolume(-VOL_STEP)}
          disabled={volBusy || ($sonos.volume ?? 0) <= VOL_FLOOR}
          aria-label="Volume down"
        >
          <VolumeX size={18} strokeWidth={1.6} />
        </button>
        <span class="vol-readout">{$sonos.volume ?? '—'}</span>
        <button
          type="button"
          class="vol-btn"
          on:click={() => bumpVolume(VOL_STEP)}
          disabled={volBusy || ($sonos.volume ?? 0) >= VOL_CEILING}
          aria-label="Volume up"
        >
          <Volume2 size={18} strokeWidth={1.6} />
        </button>
      </div>
    </div>
  </section>

  {#if activeScene}
    <section class="guest-card tuning-card">
      <div class="card-head">
        <Sliders size={20} strokeWidth={1.5} />
        <h2>Tune this scene</h2>
        <button
          type="button"
          class="reset-btn"
          on:click={resetScene}
          disabled={tuningBusy}
        >
          Reset
        </button>
      </div>

      <div class="tune-row tune-row-stack">
        <span class="tune-label">Brightness</span>
        <div
          class="brightness-card"
          class:dragging={brightnessDragging}
          class:disabled={tuningBusy}
          style="--fill-pct: {brightnessFillPct}%;"
          bind:this={brightnessCardEl}
          on:pointerdown={onBrightnessPointerDown}
          on:pointermove={onBrightnessPointerMove}
          on:pointerup={onBrightnessPointerEnd}
          on:pointercancel={onBrightnessPointerEnd}
          role="slider"
          aria-label="Scene brightness"
          aria-valuemin={-BRIGHTNESS_LEVEL_CAP}
          aria-valuemax={BRIGHTNESS_LEVEL_CAP}
          aria-valuenow={displayBrightnessLevel}
        >
          <div class="brightness-fill" aria-hidden="true"></div>
          <div class="brightness-card-content">
            <span class="brightness-card-label">Dimmer</span>
            <span class="brightness-card-readout">
              {displayBrightnessLevel === 0 ? '·' : displayBrightnessLevel > 0 ? `+${displayBrightnessLevel}` : `${displayBrightnessLevel}`}
            </span>
            <span class="brightness-card-label brightness-card-label-right">Brighter</span>
          </div>
        </div>
      </div>

      <div class="tune-row">
        <span class="tune-label">Kitchen</span>
        <button
          type="button"
          class="toggle-pill"
          class:active={!kitchenDropped}
          on:click={toggleKitchen}
          disabled={tuningBusy}
        >
          {kitchenDropped ? 'Off' : 'On'}
        </button>
      </div>

      <div class="tune-row">
        <span class="tune-label">Effect</span>
        <div class="effect-chips">
          <button
            type="button"
            class="chip"
            class:active={activeEffectOverlay === 'candle'}
            on:click={() => toggleEffect('candle')}
            disabled={tuningBusy}
          >
            🕯 Candle
          </button>
          <button
            type="button"
            class="chip"
            class:active={activeEffectOverlay === 'sparkle'}
            on:click={() => toggleEffect('sparkle')}
            disabled={tuningBusy}
          >
            ✨ Sparkle
          </button>
        </div>
      </div>
    </section>
  {/if}

  <section class="guest-card">
    <div class="card-head">
      <Sparkles size={20} strokeWidth={1.5} />
      <h2>Set the mood</h2>
    </div>
    {#if !scenesLoaded}
      <p class="muted">Loading…</p>
    {:else if scenes.length === 0}
      <p class="muted">Couldn't load scenes.</p>
    {:else}
      <div class="scene-grid">
        {#each scenes as scene}
          <button
            type="button"
            class="scene-btn"
            class:loading={activatingScene === scene.name}
            on:click={() => activateScene(scene.name)}
            disabled={sceneCooldownActive || !!activatingScene}
          >
            <div class="scene-preview">
              {#each ['1', '2', '5', '3', '4'] as lid}
                <div
                  class="scene-preview-dot"
                  style="background: {lightStateToCSS(scene.lights[lid])}"
                ></div>
              {/each}
            </div>
            <span class="scene-name">{scene.display_name}</span>
          </button>
        {/each}
      </div>
    {/if}
    {#if sceneCooldownActive}
      <p class="cooldown">Cooling down… give the lights a sec.</p>
    {/if}
  </section>

  <section class="guest-card">
    <div class="card-head">
      <Music2 size={20} strokeWidth={1.5} />
      <h2>Pick the music</h2>
    </div>
    {#if !vibesLoaded}
      <p class="muted">Loading…</p>
    {:else if vibes.length === 0}
      <p class="muted">Couldn't load vibes.</p>
    {:else}
      <div class="vibe-grid">
        {#each vibes as vibe}
          <button
            type="button"
            class="vibe-btn"
            class:loading={activatingVibe === vibe.name}
            on:click={() => activateVibe(vibe.name)}
            disabled={vibeCooldownActive || !!activatingVibe}
          >
            <span class="vibe-label">{vibe.label}</span>
            <span class="vibe-playlist">{vibe.playlist_title}</span>
          </button>
        {/each}
      </div>
    {/if}
    {#if vibeCooldownActive}
      <p class="cooldown">Cooling down… give the music a sec.</p>
    {/if}
  </section>

  <section class="guest-card">
    <div class="card-head">
      <Mic size={20} strokeWidth={1.5} />
      <h2>Send a toast</h2>
    </div>
    <p class="toast-hint">Speak it through the room. Sparkle while it plays.</p>
    <div class="toast-form">
      <input
        type="text"
        class="toast-input"
        placeholder="Say something to the room…"
        maxlength={TOAST_MAX_CHARS}
        bind:value={toastInput}
        disabled={toastSending}
      />
      <input
        type="text"
        class="toast-input"
        placeholder="Your name (optional)"
        maxlength={TOAST_NAME_MAX_CHARS}
        bind:value={toastNameInput}
        disabled={toastSending}
      />
      <button
        type="button"
        class="toast-send"
        on:click={sendToast}
        disabled={toastSending || toastCooldownRemaining > 0 || !toastInput.trim()}
      >
        {#if toastCooldownRemaining > 0}
          Wait {toastCooldownRemaining}s
        {:else if toastSending}
          Speaking…
        {:else}
          🎤 Speak it
        {/if}
      </button>
    </div>
  </section>
</main>

{#if toastMessage}
  <div class="toast" role="status">{toastMessage}</div>
{/if}

<style>
  .guest-page {
    max-width: 540px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .guest-header { text-align: center; margin-bottom: 4px; }
  .guest-header h1 {
    font-family: var(--font-display);
    font-size: 56px;
    line-height: 1;
    margin: 0 0 8px;
    letter-spacing: 0.04em;
    color: #fff;
  }
  .guest-subtitle {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.65);
    margin: 0;
  }

  .guest-card {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 18px;
    padding: 22px 24px;
    backdrop-filter: blur(12px);
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    color: rgba(245, 243, 238, 0.85);
  }
  .card-head h2 {
    font-family: var(--font-display);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
    color: rgba(245, 243, 238, 0.95);
    flex: 1;
  }

  .mode-line {
    margin-bottom: 18px;
  }
  .mode-name {
    font-family: var(--font-display);
    font-size: 32px;
    color: #fff;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  /* Horizontal row of 4 colored circles — no labels, purely a status
     snapshot of the room's current lighting palette. */
  .swatch-row {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 14px;
  }
  .swatch-dot {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.14);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
    flex-shrink: 0;
  }
  .swatch-off {
    background: rgba(255, 255, 255, 0.04) !important;
    border-style: dashed;
    box-shadow: none;
  }

  .scene-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }
  .scene-btn {
    appearance: none;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
    padding: 14px 14px 12px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    color: #fff;
    font-family: var(--font-body);
    font-size: 14px;
    cursor: pointer;
    transition: background 0.15s, transform 0.05s, border-color 0.15s;
    text-align: center;
    min-width: 0;
  }
  .scene-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.22);
  }
  .scene-btn:active:not(:disabled) {
    transform: scale(0.98);
  }
  .scene-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .scene-btn.loading {
    background: rgba(255, 255, 255, 0.2);
  }
  /* Color preview row — 4 dots showing what the scene actually looks
     like, so guests can pick by visual rather than by guessing what
     "Miami Vice" means. */
  .scene-preview {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
  }
  .scene-preview-dot {
    flex: 1;
    aspect-ratio: 1 / 1;
    max-width: 28px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  }
  .scene-name {
    font-weight: 500;
    letter-spacing: 0.01em;
    line-height: 1.2;
  }

  .vibe-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
  }
  .vibe-btn {
    appearance: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 84px;
    padding: 14px 10px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    color: #fff;
    font-family: var(--font-body);
    cursor: pointer;
    transition: background 0.15s, transform 0.05s, border-color 0.15s;
    text-align: center;
    min-width: 0;
  }
  .vibe-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.22);
  }
  .vibe-btn:active:not(:disabled) { transform: scale(0.98); }
  .vibe-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .vibe-btn.loading { background: rgba(255, 255, 255, 0.2); }
  .vibe-label {
    font-family: var(--font-display);
    font-size: 18px;
    letter-spacing: 0.04em;
    line-height: 1;
  }
  .vibe-playlist {
    font-size: 11px;
    color: rgba(245, 243, 238, 0.55);
    line-height: 1.2;
    /* Long playlist titles ("Lo-fi-working") would push the column past
       its 1fr width without min-width:0 from the parent — same trick as
       the swatch row earlier. */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }

  .cooldown {
    margin: 12px 0 0;
    font-size: 12px;
    color: rgba(245, 243, 238, 0.55);
    text-align: center;
  }

  .toast-hint {
    font-size: 13px;
    color: rgba(245, 243, 238, 0.55);
    margin: 0 0 14px;
  }
  .toast-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .toast-input {
    appearance: none;
    width: 100%;
    box-sizing: border-box;
    padding: 12px 14px;
    background: rgba(0, 0, 0, 0.28);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 12px;
    color: #fff;
    font-family: var(--font-body);
    font-size: 15px;
    transition: border-color 0.15s, background 0.15s;
  }
  .toast-input::placeholder {
    color: rgba(245, 243, 238, 0.4);
  }
  .toast-input:focus {
    outline: none;
    background: rgba(0, 0, 0, 0.4);
    border-color: rgba(255, 255, 255, 0.32);
  }
  .toast-input:disabled {
    opacity: 0.5;
  }
  .toast-send {
    appearance: none;
    width: 100%;
    padding: 14px 16px;
    background: linear-gradient(135deg, rgba(245, 178, 60, 0.85), rgba(220, 110, 60, 0.85));
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 12px;
    color: #fff;
    font-family: var(--font-display);
    font-size: 18px;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition: transform 0.05s, opacity 0.15s, filter 0.15s;
  }
  .toast-send:hover:not(:disabled) {
    filter: brightness(1.08);
  }
  .toast-send:active:not(:disabled) {
    transform: scale(0.98);
  }
  .toast-send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .muted {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.55);
    margin: 0;
  }

  .toast {
    position: fixed;
    bottom: calc(96px + env(safe-area-inset-bottom));
    left: 50%;
    transform: translateX(-50%);
    z-index: 60;
    background: rgba(0, 0, 0, 0.85);
    color: #fff;
    padding: 12px 20px;
    border-radius: 999px;
    font-size: 13px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.12);
    max-width: 90vw;
    text-align: center;
  }

  @media (max-width: 480px) {
    .guest-header h1 { font-size: 44px; }
    .mode-name { font-size: 28px; }
  }

  @media (min-width: 640px) {
    /* Wider screens (desktop preview, tablets) get 3 columns so the
       6 scenes fit in 2 tidy rows instead of stretching down 3. */
    .scene-grid {
      grid-template-columns: repeat(3, 1fr);
    }
  }

  /* "Hand it back to the host" — only renders while a manual override is
     active. Stays understated; this is the "calm down" button, not a
     headline action. */
  .handback-btn {
    appearance: none;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding: 10px 16px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 12px;
    color: rgba(245, 243, 238, 0.85);
    font-family: var(--font-body);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }
  .handback-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.28);
  }
  .handback-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* Source chip — sits inline with the mode label so the override status
     reads as "STATE · who set it". */
  .src-chip {
    display: inline-block;
    margin-left: 12px;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.08);
    color: rgba(245, 243, 238, 0.7);
    vertical-align: middle;
    letter-spacing: 0.02em;
  }
  .src-chip-guest {
    background: rgba(170, 110, 240, 0.18);
    color: rgba(220, 200, 255, 0.92);
  }

  /* Now-playing strip inside "Right now" — mirrors the strip on /guest
     home (+page.svelte) so both pages render consistently. Slimmer art
     (48px) since the card already has the swatch row above. */
  .now-playing {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 16px;
  }
  .np-art {
    width: 48px;
    height: 48px;
    border-radius: 6px;
    object-fit: cover;
    flex-shrink: 0;
  }
  .np-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .np-title {
    font-size: 14px;
    color: #fff;
    font-weight: 500;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .np-artist {
    font-size: 12px;
    color: rgba(245, 243, 238, 0.6);
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .np-empty {
    font-size: 13px;
    color: rgba(245, 243, 238, 0.5);
    margin: 16px 0 0;
  }

  /* Music transport — pause/skip on the left, vol rocker pinned right. */
  .transport-row {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .transport-btn {
    appearance: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    color: #fff;
    cursor: pointer;
    transition: background 0.15s, transform 0.05s, border-color 0.15s;
  }
  .transport-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.22);
  }
  .transport-btn:active:not(:disabled) { transform: scale(0.95); }
  .transport-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .volume-rocker {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-left: auto;
    padding: 4px 6px;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 12px;
  }
  .vol-btn {
    appearance: none;
    width: 40px;
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 0;
    color: #fff;
    cursor: pointer;
    border-radius: 8px;
    transition: background 0.15s;
  }
  .vol-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.1); }
  .vol-btn:disabled { opacity: 0.3; cursor: not-allowed; }
  .vol-readout {
    font-family: var(--font-display);
    font-size: 18px;
    color: rgba(245, 243, 238, 0.85);
    min-width: 28px;
    text-align: center;
    letter-spacing: 0.04em;
  }

  /* Wave 2 — in-scene tuning card. Renders only while a guest scene is
     active. Active toggles/chips use the same purple-tinted accent as the
     "Set by a guest" source chip so the connection reads visually. */
  .tuning-card .card-head { gap: 10px; }
  .reset-btn {
    appearance: none;
    margin-left: auto;
    padding: 4px 12px;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 999px;
    color: rgba(245, 243, 238, 0.7);
    font-family: var(--font-body);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .reset-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.08);
    color: #fff;
    border-color: rgba(255, 255, 255, 0.3);
  }
  .reset-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .tune-row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 0;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }
  .tune-row:first-of-type { border-top: 0; padding-top: 4px; }
  .tune-label {
    font-size: 13px;
    color: rgba(245, 243, 238, 0.7);
    flex-shrink: 0;
    min-width: 80px;
  }

  .tune-row-stack {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .tune-row-stack .tune-label { min-width: 0; }

  .brightness-card {
    position: relative;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    min-height: 56px;
    cursor: ew-resize;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
    transition: border-color 0.2s, opacity 0.2s;
  }
  .brightness-card.disabled { cursor: not-allowed; opacity: 0.5; }
  .brightness-card:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.4);
    outline-offset: 2px;
  }
  .brightness-fill {
    position: absolute;
    inset: 0;
    width: var(--fill-pct, 50%);
    background: linear-gradient(
      to right,
      rgba(170, 110, 240, 0.35) 0%,
      rgba(170, 110, 240, 0.35) 35%,
      transparent 100%
    );
    pointer-events: none;
    transition: width 0.2s ease;
  }
  .brightness-card.dragging .brightness-fill { transition: width 0.06s linear; }
  .brightness-card-content {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 16px;
    height: 100%;
  }
  .brightness-card-label {
    font-family: var(--font-body);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: rgba(245, 243, 238, 0.55);
  }
  .brightness-card-label-right { text-align: right; }
  .brightness-card-readout {
    font-family: var(--font-display);
    font-size: 22px;
    color: rgba(245, 243, 238, 0.95);
    letter-spacing: 0.04em;
    min-width: 40px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }

  .toggle-pill {
    appearance: none;
    margin-left: auto;
    padding: 6px 18px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 999px;
    color: rgba(245, 243, 238, 0.7);
    font-family: var(--font-body);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
    min-width: 64px;
  }
  .toggle-pill:hover:not(:disabled) { background: rgba(255, 255, 255, 0.14); }
  .toggle-pill:disabled { opacity: 0.5; cursor: not-allowed; }
  .toggle-pill.active {
    background: rgba(170, 110, 240, 0.18);
    border-color: rgba(170, 110, 240, 0.35);
    color: rgba(220, 200, 255, 0.95);
  }

  .effect-chips {
    display: flex;
    gap: 8px;
    margin-left: auto;
  }
  .chip {
    appearance: none;
    padding: 6px 14px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 999px;
    color: rgba(245, 243, 238, 0.8);
    font-family: var(--font-body);
    font-size: 13px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s, border-color 0.15s;
  }
  .chip:hover:not(:disabled) { background: rgba(255, 255, 255, 0.14); }
  .chip:disabled { opacity: 0.4; cursor: not-allowed; }
  .chip.active {
    background: rgba(170, 110, 240, 0.22);
    border-color: rgba(170, 110, 240, 0.4);
    color: rgba(230, 215, 255, 0.98);
  }
</style>
