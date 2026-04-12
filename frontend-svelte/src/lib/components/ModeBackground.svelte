<script>
  import { Canvas } from '@threlte/core'
  import { automation } from '$lib/stores/automation.js'
  import MoonScene from '$lib/backgrounds/MoonScene.svelte'
  import GenerativeCanvas from '$lib/backgrounds/GenerativeCanvas.svelte'
  import PixelScene from '$lib/backgrounds/PixelScene.svelte'
  import CityScene from '$lib/backgrounds/CityScene.svelte'
  import AuroraScene from '$lib/backgrounds/AuroraScene.svelte'

  $: mode = $automation.mode
</script>

{#if mode === 'sleeping'}
  <div class="mode-background">
    <Canvas>
      <MoonScene />
    </Canvas>
  </div>
{:else if mode === 'gaming'}
  <PixelScene />
{:else if mode === 'working'}
  <CityScene />
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
