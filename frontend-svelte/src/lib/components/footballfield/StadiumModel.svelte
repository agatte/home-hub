<script>
  /**
   * StadiumModel — wraps a glTF stadium model.
   *
   * The Awbmegames Low Poly Football Stadium is a closed bowl: its
   * main "Football Stadium" mesh is a continuous shell that occludes
   * inside-bowl camera positions and pins the broadcast camera to
   * an above-and-behind angle. We mitigate by hiding the main bowl
   * mesh on load, keeping the smaller meshes (floodlights, press
   * boxes, branding cubes) as floating ambience around the field.
   * This frees the camera to sit at a more conventional broadcast
   * angle while still reading as "in a stadium."
   */
  import { GLTF } from '@threlte/extras'

  /** Path to the GLB / glTF file. */
  export let url = '/3d/stadium.glb'

  /** Uniform scale. */
  export let scale = 0.81

  /** [x, y, z] world position. */
  export let position = [0, -2.5, 0]

  /** [x, y, z] rotation (radians). */
  export let rotation = [0, Math.PI / 2, 0]

  /**
   * Names (substring match, case-insensitive) of meshes to hide
   * after load. Default targets the main bowl shell of the
   * Awbmegames model — the giant continuous mesh that wraps the
   * field. Smaller decorative meshes (Cube.*, Object.*) remain
   * visible as ambient stadium chrome.
   */
  export let hideMeshes = ['Football Stadium']

  /**
   * After GLTF load, walk the scene tree and toggle visibility
   * on meshes whose names match any entry in `hideMeshes`. Logged
   * at info level so unexpected mesh names surface in DevTools.
   */
  function onLoad(event) {
    const data = event.detail
    if (!data?.scene) return
    const targets = hideMeshes.map((s) => s.toLowerCase())
    let hidden = 0
    let total = 0
    data.scene.traverse((obj) => {
      if (!obj.isMesh) return
      total += 1
      const name = (obj.name || '').toLowerCase()
      if (targets.some((t) => name.includes(t))) {
        obj.visible = false
        hidden += 1
      }
    })
    // eslint-disable-next-line no-console
    console.info(`[StadiumModel] ${hidden}/${total} meshes hidden`)
  }
</script>

<GLTF {url} {scale} {position} {rotation} on:load={onLoad} />
