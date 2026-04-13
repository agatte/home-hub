<script>
  import { Canvas } from '@threlte/core'
  import { automation } from '$lib/stores/automation.js'
  import MoonScene from '$lib/backgrounds/MoonScene.svelte'
  import GenerativeCanvas from '$lib/backgrounds/GenerativeCanvas.svelte'
  import PixelScene from '$lib/backgrounds/PixelScene.svelte'
  import ParallaxScene from '$lib/backgrounds/ParallaxScene.svelte'
  import AuroraScene from '$lib/backgrounds/AuroraScene.svelte'
  import { LAYER_CONFIGS } from '$lib/backgrounds/layer-config.js'

  $: mode = $automation.mode
  $: hasParallaxLayers = !!LAYER_CONFIGS[mode]
</script>

{#if mode === 'sleeping'}
  <div class="mode-background">
    <Canvas>
      <MoonScene />
    </Canvas>
  </div>
{:else if hasParallaxLayers}
  <ParallaxScene {mode} />
{:else if mode === 'gaming'}
  <PixelScene />
{:else if mode === 'relax'}
  <AuroraScene />
{:else}
  <GenerativeCanvas />
{/if}

<style>
  .mode-background {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  }
  .mode-background :global(canvas) {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
