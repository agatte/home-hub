<script>
  import { Canvas } from '@threlte/core'
  import { automation } from '$lib/stores/automation.js'
  import MoonScene from '$lib/backgrounds/MoonScene.svelte'

  $: isSleeping = $automation.mode === 'sleeping'
</script>

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
