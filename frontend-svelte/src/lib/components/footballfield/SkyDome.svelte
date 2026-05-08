<script>
  /**
   * SkyDome — HDRI environment, IBL source, and projected 3D ground.
   *
   * Wraps `<Environment>` from @threlte/extras to load a high-dynamic-
   * range equirectangular map and turn it into:
   *
   *   1. `scene.environment` — IBL sampling for PBR materials. This
   *      is the main reason PBR lights look "photoreal" without
   *      hand-tuning a dozen sources.
   *   2. `GroundedSkybox` (3D mesh) — the lower hemisphere of the
   *      equirect is re-projected onto a flat ground disc with a
   *      smooth dome rising into the upper sky. The HDRI's captured
   *      stadium grass becomes the actual visible ground.
   *
   * `isBackground={false}` — we don't paint the equirect as a flat 2D
   * backdrop; the GroundedSkybox handles showing the HDRI in 3D.
   *
   * Default asset: Poly Haven `stadium_01_2k.hdr` (CC0, sunrise grass
   * field, ~6 MB). Phase 2 will swap by weather + game time-of-day.
   */
  import { Environment } from '@threlte/extras'

  /** Path to the HDR / equirect file (relative to /static). */
  export let url = '/3d/env/stadium_01_2k.hdr'

  // The Environment component has an operator-precedence quirk in its
  // colorSpace assignment: `colorSpace ?? isCubeMap ? LinearSRGB : SRGB`
  // parses as `(colorSpace ?? isCubeMap) ? LinearSRGB : SRGB`, so an
  // unset colorSpace falls through to SRGB — invalid for HDR data
  // (Three.js logs `sRGB encoded textures have to use RGBAFormat and
  // UnsignedByteType` and skips applying the texture, leaving the
  // scene background black). Passing any truthy string makes the
  // ternary pick LinearSRGB, which is correct for HDR.
  const HDR_COLORSPACE = 'srgb-linear'

  // GroundedSkybox parameters. The skybox is a sphere with the lower
  // hemisphere flattened into a ground disc. Three.js convention:
  //
  //   - `height` is the vertical distance from the sphere equator to
  //     the flat ground disc (in object-local space).
  //   - `radius` is the sphere extent.
  //   - The mesh defaults to position [0,0,0]; the disc lands at
  //     world y = position.y - height. To put the disc at world y=0
  //     (matching our painted field), we set position.y = height.
  //
  // height=50 keeps the dome rising well above the y=30 broadcast
  // camera so plenty of sky stays visible. radius=200 is comfortably
  // outside the 100×53 field and the model floodlights at ~104 yd.
  const GROUND_PROJECTION = {
    height: 50,
    radius: 200,
    position: [0, 50, 0],
  }
</script>

<Environment
  files={url}
  isBackground={false}
  colorSpace={HDR_COLORSPACE}
  groundProjection={GROUND_PROJECTION}
/>
