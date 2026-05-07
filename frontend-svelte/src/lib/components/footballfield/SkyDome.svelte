<script>
  /**
   * SkyDome — HDRI environment + scene background.
   *
   * Wraps `<Environment>` from @threlte/extras to load a high-dynamic-
   * range equirectangular map. Two effects on the scene:
   *
   *   1. `scene.background` is set to the equirect projection — this
   *      replaces the black void around the field with the HDRI's
   *      sky/horizon.
   *   2. `scene.environment` is set to the same texture — PBR
   *      materials sample it for image-based lighting (reflections,
   *      diffuse fill). This is the key to "photoreal feel" without
   *      hand-tuning a dozen lights.
   *
   * Default asset: Poly Haven `stadium_01_2k.hdr` (CC0, sunrise grass
   * field, ~6 MB). Phase 2 will swap by weather + game time-of-day.
   */
  import { Environment } from '@threlte/extras'

  /** Path to the HDR / equirect file (relative to /static). */
  export let url = '/3d/env/stadium_01_2k.hdr'

  /** When true, also paints the scene background. Disable to keep a
   *  custom canvas/clear color while still using the HDRI for IBL. */
  export let isBackground = true

  // The Environment component has an operator-precedence quirk in its
  // colorSpace assignment: `colorSpace ?? isCubeMap ? LinearSRGB : SRGB`
  // parses as `(colorSpace ?? isCubeMap) ? LinearSRGB : SRGB`, so an
  // unset colorSpace falls through to SRGB — invalid for HDR data
  // (Three.js logs `sRGB encoded textures have to use RGBAFormat and
  // UnsignedByteType` and skips applying the texture, leaving the
  // scene background black). Passing any truthy string makes the
  // ternary pick LinearSRGB, which is correct for HDR.
  const HDR_COLORSPACE = 'srgb-linear'
</script>

<Environment files={url} {isBackground} colorSpace={HDR_COLORSPACE} />
