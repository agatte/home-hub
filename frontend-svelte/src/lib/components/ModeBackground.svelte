<script>
  import { Canvas } from '@threlte/core'
  import { automation } from '$lib/stores/automation.js'
  import MoonScene from '$lib/backgrounds/MoonScene.svelte'
  import GenerativeCanvas from '$lib/backgrounds/GenerativeCanvas.svelte'
  import PixelScene from '$lib/backgrounds/PixelScene.svelte'
  import WindowScene from '$lib/backgrounds/WindowScene.svelte'
  import LofiScene from '$lib/backgrounds/LofiScene.svelte'

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
  <WindowScene />
{:else if mode === 'relax'}
  <LofiScene />
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
