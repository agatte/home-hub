<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { apiGet } from '$lib/api.js'
  import { LAYER_CONFIGS, getSkyVariant, MUSIC_SPEED_BOOST } from './layer-config.js'
  import { fade } from 'svelte/transition'

  /** @type {string} */
  export let mode = 'working'

  let musicPlaying = false
  let weatherDesc = 'clear'
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null
  let animId = 0
  let lastTime = 0

  /** @type {HTMLDivElement[]} */
  let layerEls = []
  /** Per-layer scroll offset in pixels */
  let scrollOffsets = []

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  $: layers = LAYER_CONFIGS[mode] || []
  $: speedBoost = MUSIC_SPEED_BOOST[mode] || 0.7
  $: skyOverride = getSkyVariant(mode, weatherDesc)

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      if (data?.weather) weatherDesc = (data.weather.description || 'clear').toLowerCase()
    } catch { /* ignore */ }
  }

  function getLayerSrc(layer, index) {
    if (index === 0 && skyOverride) return skyOverride
    return layer.src
  }

  function animate(ts) {
    animId = requestAnimationFrame(animate)
    if (!lastTime) { lastTime = ts; return }
    const dt = (ts - lastTime) / 1000 // seconds
    lastTime = ts

    const speedMult = musicPlaying ? speedBoost : 1.0

    for (let i = 0; i < layers.length; i++) {
      const layer = layers[i]
      if (layer.duration === 0 || !layerEls[i]) continue

      // Pixels per second = tileWidth / duration
      // tileWidth = element height (square 1:1 images at background-size: auto 100%)
      const el = layerEls[i]
      const tileW = el.offsetHeight // square image: rendered width = element height
      const pxPerSec = tileW / (layer.duration * speedMult)

      if (!scrollOffsets[i]) scrollOffsets[i] = 0
      scrollOffsets[i] = (scrollOffsets[i] + pxPerSec * dt) % tileW

      el.style.backgroundPositionX = `-${Math.round(scrollOffsets[i])}px`
    }
  }

  onMount(async () => {
    scrollOffsets = layers.map(() => 0)
    await fetchWeather()
    weatherTimer = setInterval(fetchWeather, 600_000)
    animId = requestAnimationFrame(animate)
  })

  onDestroy(() => {
    cancelAnimationFrame(animId)
    unsub()
    if (weatherTimer) clearInterval(weatherTimer)
  })
</script>

<div class="parallax-container" transition:fade={{ duration: 500 }}>
  {#each layers as layer, i (layer.src + i)}
    <div
      class="parallax-layer"
      bind:this={layerEls[i]}
      style="
        background-image: url('{getLayerSrc(layer, i)}');
        z-index: {layer.zIndex};
        opacity: {layer.opacity};
        {layer.sizing === 'cover' ? 'background-size: cover; background-repeat: no-repeat; background-position: center bottom;' : 'background-size: auto 100%; background-repeat: repeat-x; background-position: left bottom;'}
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
    background: #050508;
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
