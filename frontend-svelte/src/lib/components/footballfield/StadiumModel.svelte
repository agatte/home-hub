<script>
  /**
   * StadiumModel — wraps a glTF stadium model.
   *
   * Phase 1a: optional. If `/3d/stadium.glb` is missing, the GLTF
   * loader logs a console error and the component renders nothing —
   * the rest of the scene (HDRI sky + PBR field + camera + ball) is
   * unaffected. Drop a GLB into the path and reload to see the
   * stadium materialise.
   *
   * Phase 1b: tune `position`, `scale`, `rotation` to align the
   * model's field with our 100×53 yard coordinate system. Most
   * Sketchfab low-poly stadiums export with their own field plane —
   * disable it via post-load mesh traversal if it Z-fights with
   * FieldSurface.
   */
  import { GLTF } from '@threlte/extras'

  /** Path to the GLB / glTF file. */
  export let url = '/3d/stadium.glb'

  /** Uniform scale. Tune by eye once the model loads. */
  export let scale = 1

  /** [x, y, z] world position. Tune to seat the model around the field. */
  export let position = [0, 0, 0]

  /** [x, y, z] rotation (radians). Most stadium models orient north-up; we rotate to align our field's long axis along X. */
  export let rotation = [0, 0, 0]
</script>

<GLTF {url} {scale} {position} {rotation} />
