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

  // Sideline press-box style camera — INSIDE the stadium bowl, at
  // moderate height, looking across the field. The Awbmegames bowl
  // (after scale 0.81) extends to z=±82 and y≈76. We sit at z=60
  // (inside the +z near wall) and y=28 (above the lower bowl). From
  // here the camera looks at origin: field is clearly visible in
  // the foreground, the opposite (z=-82) sideline wall and seating
  // form the background, and the HDRI sky shows above the open
  // bowl top.
  const CAMERA_X = 0
  const CAMERA_Y = 28
  const CAMERA_Z = 60
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
