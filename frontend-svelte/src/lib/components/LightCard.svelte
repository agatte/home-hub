<script>
  import Slider from './Slider.svelte'
  import { setLight } from '$lib/stores/init.js'

  import { LIGHT_CT_PRESETS } from '$lib/theme.js'

  /** @type {{ light_id: string, name: string, on: boolean, bri: number, hue: number, sat: number, ct?: number, colormode?: string, reachable: boolean }} */
  export let light

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

  function hueToHsl(hue, sat, bri) {
    const h = (hue / 65535) * 360
    const s = (sat / 254) * 100
    const l = (bri / 254) * 50
    return `hsl(${h}, ${s}%, ${Math.max(l, 20)}%)`
  }

  /** @type {ReturnType<typeof setTimeout> | null} */
  let debounceTimer = null
  let showPresets = false

  function debouncedUpdate(state) {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => { setLight(light.light_id, state) }, 100)
  }

  function togglePower() { setLight(light.light_id, { on: !light.on }) }
  function setBrightness(bri) { debouncedUpdate({ bri }) }
  function setColor(hue, sat) {
    setLight(light.light_id, { hue, sat })
    showPresets = false
  }

  function setCT(ct) {
    setLight(light.light_id, { ct })
    showPresets = false
  }

  /** Convert mirek to a warm-to-cool CSS gradient color for display */
  function ctToColor(ct) {
    // Simple mapping: 500 mirek (2000K) = warm orange, 153 mirek (6500K) = cool blue-white
    const t = (ct - 153) / (500 - 153) // 0 = cool, 1 = warm
    const r = Math.round(255 - t * 30)
    const g = Math.round(220 - t * 80)
    const b = Math.round(200 - t * 140)
    return `rgb(${r}, ${g}, ${b})`
  }

  $: bgColor = light.on ? hueToHsl(light.hue, light.sat, light.bri) : 'var(--text-muted)'
</script>

<div class="light-chip" class:light-on={light.on} class:light-off={!light.on}>
  <button
    class="chip-color-bar"
    style="background: {bgColor}"
    on:click={() => { if (light.on) showPresets = !showPresets }}
    aria-label="Change color"
    tabindex={light.on ? 0 : -1}
  ></button>

  <span class="chip-name">{light.name}</span>

  {#if light.on}
    <div class="chip-slider">
      <Slider value={light.bri} min={1} max={254} onChange={setBrightness} label="Brightness" />
    </div>
  {/if}

  <button
    class="chip-power"
    class:power-on={light.on}
    on:click={togglePower}
    aria-label={light.on ? 'Turn off' : 'Turn on'}
  >
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 2v6M18.36 6.64A9 9 0 1 1 5.64 6.64" stroke-linecap="round" />
    </svg>
  </button>

  {#if !light.reachable}
    <span class="chip-unreachable">Offline</span>
  {/if}

  {#if showPresets && light.on}
    <div class="chip-presets">
      <div class="preset-tabs">
        <button class="preset-tab" class:active={presetTab === 'color'} on:click={() => presetTab = 'color'}>Color</button>
        <button class="preset-tab" class:active={presetTab === 'temp'} on:click={() => presetTab = 'temp'}>Temp</button>
      </div>
      <div class="preset-dots">
        {#if presetTab === 'color'}
          {#each COLOR_PRESETS as preset}
            {@const active = light.colormode === 'hs' && Math.abs(light.hue - preset.hue) < 2000 && Math.abs(light.sat - preset.sat) < 50}
            <button
              class="chip-preset-dot"
              class:preset-active={active}
              style="background: {hueToHsl(preset.hue, preset.sat, 200)}"
              on:click={() => setColor(preset.hue, preset.sat)}
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
              on:click={() => setCT(preset.ct)}
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
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    position: relative;
  }

  .chip-color-bar {
    width: 32px;
    height: 4px;
    border-radius: 2px;
    border: none;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.3s, transform 0.15s;
    padding: 0;
  }

  .light-on .chip-color-bar:hover {
    transform: scaleY(2);
  }

  .chip-name {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    min-width: 80px;
  }

  .light-off .chip-name {
    color: var(--text-muted);
  }

  .chip-slider {
    flex: 1;
    min-width: 80px;
  }

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

  .chip-power:hover {
    background: rgba(255, 255, 255, 0.06);
  }

  .chip-power.power-on {
    color: var(--success);
  }

  .chip-unreachable {
    font-size: 10px;
    color: var(--danger);
    position: absolute;
    right: 12px;
    top: -2px;
  }

  .chip-presets {
    position: absolute;
    left: 12px;
    top: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 10px;
    background: rgba(10, 10, 15, 0.7);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    z-index: 10;
    animation: presetsIn 0.15s ease-out;
  }

  .preset-tabs {
    display: flex;
    gap: 4px;
  }

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

  .preset-dots {
    display: flex;
    gap: 6px;
  }

  @keyframes presetsIn {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .chip-preset-dot {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid transparent;
    cursor: pointer;
    transition: border-color 0.15s, transform 0.1s;
    padding: 0;
  }

  .chip-preset-dot:hover {
    transform: scale(1.15);
  }

  .chip-preset-dot.preset-active {
    border-color: var(--text-primary);
  }

  @media (max-width: 768px) {
    .chip-name {
      min-width: 60px;
      font-size: 12px;
    }
  }

  @media (max-width: 480px) {
    .light-chip {
      gap: 8px;
      padding: 8px 10px;
    }
    .chip-name {
      min-width: 0;
      font-size: 12px;
    }
    .chip-slider {
      min-width: 60px;
    }
  }
</style>
