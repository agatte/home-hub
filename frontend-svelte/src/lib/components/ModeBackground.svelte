<script>
  import { Canvas } from '@threlte/core'
  import { automation } from '$lib/stores/automation.js'
  import MoonScene from '$lib/backgrounds/MoonScene.svelte'
  import GenerativeCanvas from '$lib/backgrounds/GenerativeCanvas.svelte'

  $: isSleeping = $automation.mode === 'sleeping'
</script>

<!-- Generative canvas runs for all modes (including sleeping as underlayer) -->
<GenerativeCanvas />

<!-- MoonScene overlays on top during sleeping mode -->
{#if isSleeping}
  <div class="mode-background">
    <Canvas>
      <MoonScene />
    </Canvas>
  </div>
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
