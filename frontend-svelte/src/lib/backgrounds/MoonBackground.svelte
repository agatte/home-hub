<script>
  // Wrapper that bundles Threlte's Canvas + MoonScene into one chunk.
  // Loaded only when the mode hits "sleeping" via dynamic import in
  // ModeBackground.svelte — keeps Threlte/three.js out of the initial bundle.
  import { Canvas } from '@threlte/core'
  import MoonScene from './MoonScene.svelte'
</script>

<div class="moon-background">
  <Canvas>
    <MoonScene />
  </Canvas>
</div>

<style>
  .moon-background {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  }
  .moon-background :global(canvas) {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
