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

  /**
   * Get the effective animation duration for a layer.
   * Music playing = faster scroll.
   */
  function getLayerDuration(baseDuration) {
    if (baseDuration === 0) return 0
    return musicPlaying ? baseDuration * speedBoost : baseDuration
  }

  /**
   * Get the image source, using sky override for the sky layer.
   */
  function getLayerSrc(layer, index) {
    if (index === 0 && skyOverride) return skyOverride
    return layer.src
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
    {@const dur = getLayerDuration(layer.duration)}
    {@const src = getLayerSrc(layer, i)}
    <div
      class="parallax-layer"
      class:parallax-scroll={dur > 0}
      style="
        background-image: url('{src}');
        z-index: {layer.zIndex};
        opacity: {layer.opacity};
        {dur > 0 ? `animation-duration: ${dur}s;` : ''}
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
    inset: 0;
    background-size: auto 100%;
    background-repeat: repeat-x;
    background-position: 0 0;
    will-change: transform;
    image-rendering: auto;
  }

  .parallax-scroll {
    /* Double-width trick: the image tiles via repeat-x, and we translate
       by exactly one image-width so it loops seamlessly. We use 100vw as
       the translation distance since background-size: auto 100% means
       the image scales to viewport height and the width follows aspect ratio.
       For 1920x1080 assets on a 1080p screen this is exact. */
    animation: parallaxScroll linear infinite;
  }

  @keyframes parallaxScroll {
    from { transform: translateX(0); }
    to   { transform: translateX(-1920px); }
  }

  /* For high-DPI or wider screens, we need the layer to be wide enough
     to cover the viewport + one tile width for seamless looping */
  .parallax-scroll {
    width: calc(100% + 1920px);
  }

  @media (prefers-reduced-motion: reduce) {
    .parallax-scroll {
      animation: none;
    }
  }
</style>
