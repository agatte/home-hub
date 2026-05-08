<script>
  /**
   * PostFX — post-processing pipeline (bloom + ACES tone mapping).
   *
   * Replaces Threlte's default renderer.render() with an
   * EffectComposer that runs a render pass through a stack of
   * effects:
   *
   *   1. RenderPass     — renders the scene normally to an
   *      offscreen framebuffer.
   *   2. BloomEffect    — picks up bright pixels (above luminance
   *      threshold, e.g. emissive stadium lamps + sun glints on
   *      the HDRI horizon) and adds a soft glow. Gives the
   *      "broadcast HDR" feel.
   *   3. ToneMappingEffect (ACES Filmic) — compresses HDR scene
   *      radiance to LDR for display. Replaces the renderer's
   *      built-in tone mapping (set to NoToneMapping in the
   *      parent <Canvas> via the toneMapping prop) so we don't
   *      double-apply.
   *
   * Requires `<Canvas autoRender={false}>` so this component's
   * useTask is the sole driver of frame rendering. Threlte's
   * scheduler runs tasks in component-mount order; place this
   * component LAST in the scene tree so all other tasks update
   * scene state before we render.
   */
  import { onDestroy } from 'svelte'
  import { useTask, useThrelte } from '@threlte/core'
  import {
    EffectComposer,
    RenderPass,
    EffectPass,
    BloomEffect,
    ToneMappingEffect,
    ToneMappingMode,
    BlendFunction,
    KernelSize,
  } from 'postprocessing'

  /** Bloom intensity. Higher = more glow on bright pixels. */
  export let bloomIntensity = 1.0

  /** Bloom luminance threshold. Pixels above this brightness bloom. */
  export let bloomThreshold = 0.8

  const { renderer, scene, camera, size, invalidate } = useThrelte()

  let composer

  function buildComposer(currentCamera) {
    const c = new EffectComposer(renderer)
    c.addPass(new RenderPass(scene, currentCamera))

    const bloom = new BloomEffect({
      blendFunction: BlendFunction.ADD,
      luminanceThreshold: bloomThreshold,
      luminanceSmoothing: 0.3,
      intensity: bloomIntensity,
      kernelSize: KernelSize.LARGE,
    })

    const tonemap = new ToneMappingEffect({
      mode: ToneMappingMode.ACES_FILMIC,
    })

    c.addPass(new EffectPass(currentCamera, bloom, tonemap))
    return c
  }

  // Build the composer once the camera is mounted. The makeDefault
  // <PerspectiveCamera> in BroadcastCamera.svelte populates the
  // useThrelte camera store on its first tick.
  $: if (renderer && $camera && !composer) {
    composer = buildComposer($camera)
    invalidate()
  }

  // Keep the framebuffer sized to the canvas.
  $: if (composer && $size) {
    composer.setSize($size.width, $size.height, false)
  }

  // Drive rendering. The parent Canvas should have autoRender={false}
  // so Threlte's default render call doesn't compete with composer.render.
  useTask((delta) => {
    if (composer) composer.render(delta)
  })

  onDestroy(() => {
    if (composer) composer.dispose()
  })
</script>
