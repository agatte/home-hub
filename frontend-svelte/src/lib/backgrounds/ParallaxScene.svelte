<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { apiGet } from '$lib/api.js'
  import { LAYER_CONFIGS, MUSIC_SPEED_BOOST } from './layer-config.js'
  import { fade } from 'svelte/transition'

  /** @type {string} */
  export let mode = 'working'

  let musicPlaying = false
  let weatherDesc = 'clear'
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null
  let animId = 0
  let lastTime = 0
  // 60fps cap — matches CSS-pixel scrolling needs, prevents 144Hz monitors
  // from doing ~9× the work for no visual improvement.
  const FRAME_INTERVAL_MS = 1000 / 60
  let lastFrame = 0

  /** @type {HTMLDivElement[]} */
  let layerEls = []
  let scrollOffsets = []

  // Sky gradient colors based on time/weather
  let skyGradient = ''

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  $: layers = LAYER_CONFIGS[mode] || []
  $: speedBoost = MUSIC_SPEED_BOOST[mode] || 0.7

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      if (data?.weather) weatherDesc = (data.weather.description || 'clear').toLowerCase()
    } catch { /* ignore */ }
    updateSkyGradient()
  }

  function updateSkyGradient() {
    const hour = new Date().getHours()
    const rainy = weatherDesc.includes('rain') || weatherDesc.includes('drizzle') || weatherDesc.includes('thunderstorm')
    const overcast = weatherDesc.includes('cloud') || weatherDesc.includes('overcast')

    if (rainy) {
      skyGradient = 'linear-gradient(to bottom, #0a0a12 0%, #141420 40%, #1a1a2a 100%)'
    } else if (hour >= 6 && hour < 8) {
      skyGradient = 'linear-gradient(to bottom, #0a0818 0%, #1a1030 30%, #4a2040 60%, #c06030 100%)'
    } else if (hour >= 8 && hour < 17) {
      if (overcast) {
        skyGradient = 'linear-gradient(to bottom, #1a1a28 0%, #252535 40%, #353548 100%)'
      } else {
        skyGradient = 'linear-gradient(to bottom, #0a1025 0%, #122040 30%, #1a3560 60%, #2a5080 100%)'
      }
    } else if (hour >= 17 && hour < 20) {
      skyGradient = 'linear-gradient(to bottom, #0a0820 0%, #251040 30%, #6a2545 60%, #c07035 100%)'
    } else {
      skyGradient = 'linear-gradient(to bottom, #030308 0%, #06060f 30%, #0a0a18 100%)'
    }
  }

  function animate(ts) {
    animId = requestAnimationFrame(animate)
    // 60fps throttle — skip frames between intervals.
    if (ts - lastFrame < FRAME_INTERVAL_MS) return
    lastFrame = ts

    if (!lastTime) { lastTime = ts; return }
    const dt = (ts - lastTime) / 1000
    lastTime = ts

    const speedMult = musicPlaying ? speedBoost : 1.0

    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i]
      if (layer.duration === 0 || !layerEls[i]) continue

      const el = layerEls[i]
      const tileW = el.offsetHeight
      const pxPerSec = tileW / (layer.duration * speedMult)

      if (!scrollOffsets[i]) scrollOffsets[i] = 0
      scrollOffsets[i] = (scrollOffsets[i] + pxPerSec * dt) % tileW

      el.style.backgroundPositionX = `-${Math.round(scrollOffsets[i])}px`
    }
  }

  onMount(async () => {
    scrollOffsets = layers.map(() => 0)
    updateSkyGradient()
    await fetchWeather()
    weatherTimer = setInterval(fetchWeather, 600_000)

    // Skip the rAF loop entirely when prefers-reduced-motion is set —
    // the CSS rule already pins background-position, and there's no point
    // burning cycles writing to a property the browser will override.
    const reduceMotion =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (!reduceMotion) {
      animId = requestAnimationFrame(animate)
    }
  })

  onDestroy(() => {
    cancelAnimationFrame(animId)
    unsub()
    if (weatherTimer) clearInterval(weatherTimer)
  })
</script>

<div class="parallax-container" transition:fade={{ duration: 500 }}>
  <!-- Code-drawn sky gradient (no PNG needed) -->
  <div class="sky-layer" style="background: {skyGradient};"></div>

  <!-- Image layers -->
  {#each layers as layer, i (layer.src + i)}
    <div
      class="parallax-layer"
      bind:this={layerEls[i]}
      style="
        background-image: url('{layer.src}');
        z-index: {layer.zIndex};
        opacity: {layer.opacity};
        background-size: auto 100%;
        background-repeat: repeat-x;
        background-position: left bottom;
        {layer.anchor === 'bottom' && layer.height ? `top: auto; height: ${layer.height};` : ''}
      "
    ></div>
  {/each}
</div>

<style>
  .parallax-container {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
    background: #030308;
  }

  .sky-layer {
    position: absolute;
    inset: 0;
    z-index: 0;
  }

  .parallax-layer {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    top: 0;
    image-rendering: auto;
  }

  @media (prefers-reduced-motion: reduce) {
    .parallax-layer {
      background-position: left bottom !important;
    }
  }
</style>
