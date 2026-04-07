<script>
  import { Canvas } from '@threlte/core'
  import MoonScene from '$lib/MoonScene.svelte'
</script>

<div class="stage">
  <Canvas>
    <MoonScene />
  </Canvas>

  <div class="caption">
    <div class="caption-label">Sleeping</div>
    <div class="caption-time">10:42 PM</div>
  </div>
</div>

<style>
  .stage {
    position: fixed;
    inset: 0;
    background: #000;
  }

  .caption {
    position: absolute;
    bottom: 32px;
    left: 32px;
    pointer-events: none;
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
  }

  .caption-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: rgba(232, 233, 237, 0.6);
    margin-bottom: 4px;
  }

  .caption-time {
    font-size: 28px;
    font-weight: 300;
    color: #e8e9ed;
    letter-spacing: -0.5px;
  }
</style>
