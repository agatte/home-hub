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

  // Camera at midfield press-box height, ~70 yards back from the
  // sideline. atan2(35, 70) ≈ 0.4636 rad ≈ 26.6° pitch.
  const CAMERA_PITCH = -Math.atan2(35, 70)
</script>

<T.PerspectiveCamera
  makeDefault
  position={[0, 35, 70]}
  rotation={[CAMERA_PITCH, 0, 0]}
  fov={50}
  near={0.5}
  far={500}
/>
