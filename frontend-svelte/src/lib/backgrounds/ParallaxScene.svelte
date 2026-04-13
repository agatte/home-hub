<script>
  import { onMount, onDestroy } from 'svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { apiGet } from '$lib/api.js'
  import { LAYER_CONFIGS, TILE_WIDTH, getSkyVariant, MUSIC_SPEED_BOOST } from './layer-config.js'
  import { fade } from 'svelte/transition'

  /** @type {string} */
  export let mode = 'working'

  let musicPlaying = false
  let weatherDesc = 'clear'
  /** @type {ReturnType<typeof setInterval> | null} */
  let weatherTimer = null

  const unsub = sonos.subscribe(($s) => { musicPlaying = $s.state === 'PLAYING' })

  $: layers = LAYER_CONFIGS[mode] || []
  $: speedBoost = MUSIC_SPEED_BOOST[mode] || 0.7

  // Sky override based on weather/time — only recompute when weatherDesc changes
  let skyOverride = ''
  $: skyOverride = getSkyVariant(mode, weatherDesc)

  async function fetchWeather() {
    try {
      const data = await apiGet('/api/weather')
      if (data?.weather) weatherDesc = (data.weather.description || 'clear').toLowerCase()
    } catch { /* ignore */ }
  }

  function getLayerDuration(baseDuration) {
    if (baseDuration === 0) return 0
    return musicPlaying ? baseDuration * speedBoost : baseDuration
  }

  function getLayerSrc(layer, index) {
    // Sky layer (index 0) can be swapped for weather/time variants
    if (index === 0 && skyOverride) return skyOverride
    return layer.src
  }

  function getLayerStyle(layer, index) {
    const dur = getLayerDuration(layer.duration)
    const src = getLayerSrc(layer, index)
    const isTile = layer.sizing === 'tile'
    const isBottom = layer.anchor === 'bottom'

    let style = `background-image: url('${src}');`
    style += `z-index: ${layer.zIndex};`
    style += `opacity: ${layer.opacity};`

    if (isTile) {
      // Tile horizontally, scale height to fill the layer's portion
      style += `background-size: auto 100%;`
      style += `background-repeat: repeat-x;`
      style += `background-position: bottom left;`
    } else {
      // Cover — stretch to fill
      style += `background-size: cover;`
      style += `background-repeat: no-repeat;`
      style += `background-position: center;`
    }

    if (isBottom && layer.height) {
      style += `top: auto; height: ${layer.height};`
    }

    if (dur > 0) {
      style += `animation-duration: ${dur}s;`
    }

    return style
  }

  onMount(async () => {
    await fetchWeather()
    weatherTimer = setInterval(fetchWeather, 600_000)
  })

  onDestroy(() => {
    unsub()
    if (weatherTimer) clearInterval(weatherTimer)
  })
</script>

<div class="parallax-container" transition:fade={{ duration: 500 }}>
  {#each layers as layer, i (layer.src)}
    <div
      class="parallax-layer"
      class:parallax-scroll={layer.duration > 0}
      style={getLayerStyle(layer, i)}
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
    will-change: transform;
    image-rendering: auto;
  }

  .parallax-scroll {
    animation: parallaxScroll linear infinite;
    /* Extend width by one tile so the repeat covers the seam during scroll */
    width: calc(100% + 1024px);
  }

  @keyframes parallaxScroll {
    from { transform: translateX(0); }
    to   { transform: translateX(-1024px); }
  }

  @media (prefers-reduced-motion: reduce) {
    .parallax-scroll {
      animation: none;
    }
  }
</style>
