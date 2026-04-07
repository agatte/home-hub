<script>
  import Slider from './Slider.svelte'
  import { setLight } from '$lib/stores/init.js'

  /** @type {{ light_id: string, name: string, on: boolean, bri: number, hue: number, sat: number, reachable: boolean }} */
  export let light

  // Ported verbatim from frontend/src/components/lights/LightCard.jsx —
  // same presets, same proximity thresholds (<2000 hue, <50 sat), same
  // 100ms brightness debounce, same hue→HSL conversion with 20% min lightness.
  const COLOR_PRESETS = [
    { name: 'Warm',     hue: 8000,  sat: 140 },
    { name: 'Cool',     hue: 34000, sat: 50 },
    { name: 'Daylight', hue: 41000, sat: 30 },
    { name: 'Blue',     hue: 46920, sat: 254 },
    { name: 'Red',      hue: 0,     sat: 254 },
    { name: 'Green',    hue: 25500, sat: 254 },
    { name: 'Purple',   hue: 50000, sat: 254 },
  ]

  /**
   * @param {number} hue
   * @param {number} sat
   * @param {number} bri
   */
  function hueToHsl(hue, sat, bri) {
    const h = (hue / 65535) * 360
    const s = (sat / 254) * 100
    const l = (bri / 254) * 50
    return `hsl(${h}, ${s}%, ${Math.max(l, 20)}%)`
  }

  /** @type {ReturnType<typeof setTimeout> | null} */
  let debounceTimer = null

  /** @param {Record<string, unknown>} state */
  function debouncedUpdate(state) {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      setLight(light.light_id, state)
    }, 100)
  }

  function togglePower() {
    setLight(light.light_id, { on: !light.on })
  }

  /** @param {number} bri */
  function setBrightness(bri) {
    debouncedUpdate({ bri })
  }

  /** @param {number} hue @param {number} sat */
  function setColor(hue, sat) {
    setLight(light.light_id, { hue, sat })
  }

  $: bgColor = light.on ? hueToHsl(light.hue, light.sat, light.bri) : '#1a1a2e'
</script>

<div class="light-card" class:light-on={light.on} class:light-off={!light.on}>
  <div class="light-header">
    <div class="light-indicator" style="background: {light.on ? bgColor : '#333'}"></div>
    <span class="light-name">{light.name}</span>
    <button
      class="power-btn"
      class:power-on={light.on}
      on:click={togglePower}
      aria-label={light.on ? 'Turn off' : 'Turn on'}
    >
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2v6M18.36 6.64A9 9 0 1 1 5.64 6.64" stroke-linecap="round" />
      </svg>
    </button>
  </div>

  {#if light.on}
    <Slider value={light.bri} min={1} max={254} onChange={setBrightness} label="Brightness" />
    <div class="color-presets">
      {#each COLOR_PRESETS as preset}
        {@const active = Math.abs(light.hue - preset.hue) < 2000 && Math.abs(light.sat - preset.sat) < 50}
        <button
          class="color-preset"
          class:color-active={active}
          style="background: {hueToHsl(preset.hue, preset.sat, 200)}"
          on:click={() => setColor(preset.hue, preset.sat)}
          title={preset.name}
        ></button>
      {/each}
    </div>
  {/if}

  {#if !light.reachable}
    <div class="light-unreachable">Unreachable</div>
  {/if}
</div>
