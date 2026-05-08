<script>
  /**
   * SkyDome — HDRI environment, IBL source, and projected 3D ground.
   *
   * Loads the Poly Haven `stadium_01_2k.hdr` equirect via RGBELoader
   * and uses it for two things:
   *
   *   1. `scene.environment` — IBL sampling for PBR materials in the
   *      scene (endzone meshes, ball, anything else with
   *      MeshStandardMaterial). Without this PBR materials look flat.
   *   2. `GroundedSkybox` mesh — re-projects the lower hemisphere of
   *      the equirect onto a flat ground disc with a smooth dome
   *      rising into the upper sky. The HDRI's captured stadium
   *      grass becomes the actual visible ground beneath the
   *      camera; the upper hemisphere stays as the sky.
   *
   * We import `RGBELoader` and `GroundedSkybox` directly rather than
   * going through `@threlte/extras`' `<Environment>` + `groundProjection`
   * prop. The Threlte component uses a runtime dynamic import for
   * `three/examples/jsm/objects/GroundedSkybox.js` with `@vite-ignore`,
   * which fails in the browser ("Failed to resolve module specifier")
   * because bare specifiers aren't browser-resolvable. Static imports
   * here let Vite bundle the modules normally.
   *
   * Default asset: Poly Haven `stadium_01_2k.hdr` (CC0, sunrise grass
   * field, ~6 MB). Phase 2 will swap by weather + game time-of-day.
   */
  import { T, useLoader, useThrelte } from '@threlte/core'
  import { onDestroy } from 'svelte'
  import {
    EquirectangularReflectionMapping,
    FloatType,
    LinearSRGBColorSpace,
  } from 'three'
  import { RGBELoader } from 'three/examples/jsm/loaders/RGBELoader.js'
  import { GroundedSkybox } from 'three/examples/jsm/objects/GroundedSkybox.js'

  /** Path to the HDR / equirect file (relative to /static). */
  export let url = '/3d/env/stadium_01_2k.hdr'

  // GroundedSkybox parameters. The skybox is a sphere with the lower
  // hemisphere flattened into a ground disc. Three.js convention:
  //
  //   - `height` is the vertical distance from the sphere equator to
  //     the flat ground disc (in object-local space).
  //   - `radius` is the sphere extent.
  //   - The mesh defaults to position [0,0,0]; the disc lands at
  //     world y = position.y - height. To put the disc at world y=0
  //     (matching our painted field), we set position.y = HEIGHT.
  //
  // HEIGHT=50 keeps the dome rising well above the y=30 broadcast
  // camera so plenty of sky stays visible. RADIUS=200 is comfortably
  // outside the 100×53 field and the model floodlights at ~104 yd.
  const HEIGHT = 50
  const RADIUS = 200

  const { scene, invalidate } = useThrelte()

  // useLoader caches by (loader, url) so repeated loads of the same
  // HDR across components don't re-fetch.
  const loader = useLoader(RGBELoader, {
    extend: (l) => l.setDataType(FloatType),
  })
  const textureStore = loader.load(url, {
    transform: (tex) => {
      tex.mapping = EquirectangularReflectionMapping
      tex.colorSpace = LinearSRGBColorSpace
      return tex
    },
  })

  // Set scene.environment for IBL once the texture loads. Restore on
  // destroy so navigating away doesn't leak the env map onto the
  // global scene.
  const previousEnv = scene.environment
  $: if ($textureStore) {
    scene.environment = $textureStore
    invalidate()
  }

  onDestroy(() => {
    scene.environment = previousEnv
    invalidate()
  })
</script>

{#if $textureStore}
  <T
    is={GroundedSkybox}
    args={[$textureStore, HEIGHT, RADIUS]}
    position={[0, HEIGHT, 0]}
  />
{/if}
