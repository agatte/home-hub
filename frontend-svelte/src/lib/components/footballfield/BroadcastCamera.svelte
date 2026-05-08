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

  // Sideline broadcast camera. With StadiumModel hiding the bowl
  // shell on load, the camera no longer has to fly above y=76 to
  // clear the wall — the floodlights, press boxes, and signage
  // remain visible at the edges of frame as floating ambience.
  // pitch = atan2(30, 75) ≈ 21.8° — natural broadcast angle.
  const CAMERA_X = 0
  const CAMERA_Y = 30
  const CAMERA_Z = 75
  const CAMERA_PITCH = -Math.atan2(CAMERA_Y, CAMERA_Z)
</script>

<T.PerspectiveCamera
  makeDefault
  position={[CAMERA_X, CAMERA_Y, CAMERA_Z]}
  rotation={[CAMERA_PITCH, 0, 0]}
  fov={50}
  near={0.5}
  far={500}
/>
