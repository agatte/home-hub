<script>
  import { onDestroy, onMount } from 'svelte'
  import {
    Sparkles, Gamepad2, Monitor, Tv, PartyPopper, Flame, ChefHat, Moon, Bot,
    Music2,
  } from 'lucide-svelte'
  import { lights } from '$lib/stores/lights.js'
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

  // Stable order matching the apartment's L1..L4 layout.
  $: orderedLights = ['1', '2', '3', '4'].map((id) => $lights[id]).filter(Boolean)

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

  onMount(async () => {
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
  })
</script>

<svelte:head>
  <title>Vibe — Home Hub</title>
</svelte:head>

<main class="guest-page">
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
  </section>

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
              {#each ['1', '2', '3', '4'] as lid}
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
</style>
