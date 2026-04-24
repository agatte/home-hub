<script>
  import { onDestroy } from 'svelte'
  import { automation } from '$lib/stores/automation.js'
  import GenerativeCanvas from '$lib/backgrounds/GenerativeCanvas.svelte'
  import PixelScene from '$lib/backgrounds/PixelScene.svelte'
  import ParallaxScene from '$lib/backgrounds/ParallaxScene.svelte'
  import AuroraScene from '$lib/backgrounds/AuroraScene.svelte'
  import { LAYER_CONFIGS } from '$lib/backgrounds/layer-config.js'

  $: mode = $automation.mode
  $: hasParallaxLayers = !!LAYER_CONFIGS[mode]

  // MoonBackground (Threlte + three.js, ~600KB) is only used in sleeping mode.
  // Dynamic-import it on demand so the kiosk's first paint isn't paying that
  // bundle cost on every page load.
  /** @type {any} */
  let MoonComponent = null
  let moonLoading = false
  let moonError = false

  $: if (mode === 'sleeping' && !MoonComponent && !moonLoading && !moonError) {
    moonLoading = true
    import('$lib/backgrounds/MoonBackground.svelte')
      .then(m => { MoonComponent = m.default })
      .catch(err => {
        moonError = true
        console.error('[ModeBackground] failed to load MoonBackground:', err)
      })
      .finally(() => { moonLoading = false })
  }

  onDestroy(() => {
    // Help GC release the chunk reference if the layout itself is destroyed.
    MoonComponent = null
  })
</script>

{#if mode === 'sleeping'}
  {#if MoonComponent}
    <svelte:component this={MoonComponent} />
  {:else if moonError}
    <!-- Fallback to generative canvas if the chunk fails to load -->
    <GenerativeCanvas />
  {/if}
{:else if hasParallaxLayers}
  <ParallaxScene {mode} />
{:else if mode === 'gaming'}
  <PixelScene />
{:else if mode === 'relax'}
  <AuroraScene />
{:else}
  <GenerativeCanvas />
{/if}
