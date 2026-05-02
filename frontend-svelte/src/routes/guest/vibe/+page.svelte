<script>
  import { onDestroy } from 'svelte'
  import { Sparkles, Zap, Sunset, Moon } from 'lucide-svelte'
  import { lights } from '$lib/stores/lights.js'
  import { automation } from '$lib/stores/automation.js'
  import { modeLabel, modeColor } from '$lib/theme.js'

  // Hue API hue is 0..65535. Convert to a CSS hsl angle.
  function hueToHsl(h, s, bri) {
    const angle = Math.round(((h ?? 0) / 65535) * 360)
    const sat = Math.round(((s ?? 0) / 254) * 100)
    // Compress brightness so even bri=20 still reads as a faint glow,
    // not pitch black. 35% min, 85% max.
    const light = 35 + Math.round(((bri ?? 0) / 254) * 50)
    return `hsl(${angle}, ${sat}%, ${light}%)`
  }

  // Color-mode (ct) lights have no hue/sat. Approximate from mirek
  // (153=cool 6500K, 500=warm 2000K) via a warm-white gradient.
  function ctToHsl(ct, bri) {
    if (!ct) return '#888'
    const t = Math.min(1, Math.max(0, (ct - 153) / (500 - 153)))
    const angle = 50 - t * 20  // 50° (cool yellow) → 30° (warm orange)
    const sat = 60 + t * 30
    const light = 50 + Math.round(((bri ?? 0) / 254) * 30)
    return `hsl(${angle}, ${sat}%, ${light}%)`
  }

  function lightSwatch(light) {
    if (!light?.on) return 'transparent'
    if (light.colormode === 'ct' || (light.ct && !light.hue)) {
      return ctToHsl(light.ct, light.bri)
    }
    return hueToHsl(light.hue, light.sat, light.bri)
  }

  // Stable order matching the apartment's L1..L4 layout.
  $: orderedLights = ['1', '2', '3', '4'].map((id) => $lights[id]).filter(Boolean)

  const SCENES = [
    { name: 'party',  label: 'Party',  icon: Sparkles },
    { name: 'neon',   label: 'Neon',   icon: Zap },
    { name: 'sunset', label: 'Sunset', icon: Sunset },
    { name: 'chill',  label: 'Chill',  icon: Moon },
  ]

  /** @type {string | null} */
  let activatingScene = null
  /** @type {boolean} */
  let cooldownActive = false
  /** @type {string | null} */
  let toastMessage = null
  /** @type {ReturnType<typeof setTimeout> | null} */
  let toastTimer = null
  /** @type {ReturnType<typeof setTimeout> | null} */
  let cooldownTimer = null

  function showToast(msg) {
    toastMessage = msg
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toastMessage = null }, 3000)
  }

  function startCooldown(seconds) {
    cooldownActive = true
    if (cooldownTimer) clearTimeout(cooldownTimer)
    cooldownTimer = setTimeout(() => { cooldownActive = false }, seconds * 1000)
  }

  async function activateScene(name) {
    if (cooldownActive || activatingScene) return
    activatingScene = name
    try {
      const res = await fetch(`/api/guest/scene/${name}`, { method: 'POST' })
      if (res.status === 429) {
        const body = await res.json().catch(() => ({}))
        const retryAfter = parseInt(res.headers.get('Retry-After') ?? '60', 10) || 60
        startCooldown(retryAfter)
        showToast(body.detail || `Cooling down — try again in ${retryAfter}s`)
        return
      }
      if (!res.ok) {
        showToast(`Couldn't change the lights (${res.status})`)
        return
      }
      const body = await res.json()
      startCooldown(body.cooldown_seconds ?? 60)
      const sceneLabel = body.scene || name
      showToast(`Lights set to ${sceneLabel}`)
    } catch {
      showToast(`Couldn't reach the server`)
    } finally {
      activatingScene = null
    }
  }

  onDestroy(() => {
    if (toastTimer) clearTimeout(toastTimer)
    if (cooldownTimer) clearTimeout(cooldownTimer)
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
      <span class="mode-dot" style="background: {modeColor($automation.mode)}"></span>
      <h2>Right now</h2>
    </div>
    <div class="mode-line">
      <span class="mode-name">{modeLabel($automation.mode)}</span>
    </div>
    <div class="swatches">
      {#each orderedLights as light}
        <div class="swatch-wrap">
          <div
            class="swatch"
            class:swatch-off={!light.on}
            style="background: {lightSwatch(light)}"
          ></div>
          <div class="swatch-label">{light.name || `L${light.light_id}`}</div>
        </div>
      {/each}
    </div>
  </section>

  <section class="guest-card">
    <div class="card-head">
      <Sparkles size={20} strokeWidth={1.5} />
      <h2>Set the mood</h2>
    </div>
    <div class="scene-grid">
      {#each SCENES as scene}
        <button
          type="button"
          class="scene-btn"
          class:loading={activatingScene === scene.name}
          on:click={() => activateScene(scene.name)}
          disabled={cooldownActive || !!activatingScene}
        >
          <svelte:component this={scene.icon} size={22} strokeWidth={1.5} />
          <span>{scene.label}</span>
        </button>
      {/each}
    </div>
    {#if cooldownActive}
      <p class="cooldown">Cooling down… give the lights a sec.</p>
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

  .mode-dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    box-shadow: 0 0 14px currentColor;
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

  .swatches {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }
  .swatch-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    /* Without this, long labels (e.g. "Living room lamp") inflate the
       grid column past its 1fr share and push the row off-screen on
       phone widths. min-width:0 lets the column collapse to its track
       size and the label clip via text-overflow: ellipsis. */
    min-width: 0;
  }
  .swatch {
    width: 100%;
    aspect-ratio: 1 / 1;
    border-radius: 14px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3);
  }
  .swatch-off {
    background: repeating-linear-gradient(
      45deg,
      rgba(255, 255, 255, 0.04),
      rgba(255, 255, 255, 0.04) 4px,
      transparent 4px,
      transparent 8px
    ) !important;
  }
  .swatch-label {
    font-size: 11px;
    color: rgba(245, 243, 238, 0.55);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    text-align: center;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
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
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 80px;
    padding: 16px 12px;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    color: #fff;
    font-family: var(--font-body);
    font-size: 15px;
    cursor: pointer;
    transition: background 0.15s, transform 0.05s;
  }
  .scene-btn:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.14);
  }
  .scene-btn:active:not(:disabled) {
    transform: scale(0.98);
  }
  .scene-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .scene-btn.loading {
    background: rgba(255, 255, 255, 0.18);
  }

  .cooldown {
    margin: 12px 0 0;
    font-size: 12px;
    color: rgba(245, 243, 238, 0.55);
    text-align: center;
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
    /* 4-up swatches squeeze labels to ~67px wide on a 390px iPhone —
       cramped enough that the labels ellipsis to nothing useful. 2x2
       gives each swatch ~140px to breathe and the labels fit on one
       line. */
    .swatches {
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
    }
    .swatch {
      max-width: 120px;
      margin: 0 auto;
    }
    .swatch-label {
      white-space: normal;
      overflow: visible;
      text-overflow: clip;
    }
  }
</style>
