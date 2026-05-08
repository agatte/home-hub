<script>
  /**
   * BroadcastCamera — locked-preset broadcast camera for the FieldScene.
   *
   * Phase 1: static. Position [0, 35, 70] looking at origin gives a
   * ~26.6° pitch from horizontal — a TV-broadcast overhead-side view
   * with the field's long axis stretching left-to-right on screen.
   *
   * Phase 3 will replace this with `camera-controls` + cinematic
   * dynamics (slow orbit during pregame, snap-to-broadcast on plays,
   * dolly-in for celebrations). The component shape is preserved so
   * that swap is a one-file change.
   */
  import { T } from '@threlte/core'

  // Reserved for phase 3 — currently unused, but kept on the prop
  // surface so the camera component owns motion concerns end-to-end.
  // eslint-disable-next-line no-unused-vars
  export let reduceMotion = false
  reduceMotion;

  // Above-and-behind-the-bowl angle. The Awbmegames stadium model
  // is a continuous closed shell — its bowl walls (z=±82, y up to
  // 76.5) and underlying seat slope mean any inside-bowl camera
  // position sits inside or under the mesh, and back-face culling
  // renders nothing. Putting the camera at [0, 110, 110] guarantees
  // a clear line of sight: at z=82 the line of sight reaches y=82,
  // above the bowl wall top of 76.5. Pitch = atan2(110, 110) = 45°.
  //
  // Trade-off: the field appears smaller in frame because we're
  // looking at the whole stadium from above. To zoom in tighter
  // without blocking the wall, this would need the bowl walls
  // hidden via mesh traversal — deferred for a future iteration.
  const CAMERA_X = 0
  const CAMERA_Y = 110
  const CAMERA_Z = 110
  const CAMERA_PITCH = -Math.atan2(CAMERA_Y, CAMERA_Z)
</script>

<T.PerspectiveCamera
  makeDefault
  position={[CAMERA_X, CAMERA_Y, CAMERA_Z]}
  rotation={[CAMERA_PITCH, 0, 0]}
  fov={45}
  near={0.5}
  far={1000}
/>
