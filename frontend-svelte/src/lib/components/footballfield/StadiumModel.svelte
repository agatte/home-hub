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
   * after load. Sketchfab strips spaces from mesh names — actual
   * runtime names are `Football_Stadium_Color_0`, `Cube004_Color_0`,
   * etc. Defaults catch:
   *   - `stadium` → Football_Stadium + Football_Stadium003 (the
   *     bowl shell + the model's painted soccer field surface)
   *   - `cube`    → Cube004/013/014/021 (Awbmegames is a soccer
   *     model: these are the soccer goals + a couple of white
   *     "bench" prop boxes near the field — off-genre clutter for
   *     our American football scene)
   * The remaining `Object001-006` meshes stay visible — they're
   * the floodlight towers / press box structures that read as
   * stadium ambience.
   */
  export let hideMeshes = ['stadium', 'cube']

  /**
   * After GLTF load, walk the scene tree and toggle visibility
   * on meshes whose names match any entry in `hideMeshes`. Logged
   * at info level so unexpected mesh names surface in DevTools.
   */
  // @threlte/extras' GLTF uses createRawEventDispatcher — the handler
  // receives the gltf object directly (not wrapped in CustomEvent.detail).
  function onLoad(gltf) {
    if (!gltf?.scene) return
    const targets = hideMeshes.map((s) => s.toLowerCase())
    gltf.scene.traverse((obj) => {
      if (!obj.isMesh) return
      const name = (obj.name || '').toLowerCase()
      if (targets.some((t) => name.includes(t))) {
        obj.visible = false
      }
    })
  }
</script>

<GLTF {url} {scale} {position} {rotation} on:load={onLoad} />
