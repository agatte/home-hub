export const CONTEXT_CAMERA_POSES = Object.freeze({
  rest: Object.freeze({
    id: 'rest',
    label: 'Whole apartment',
    strategy: 'camera-policy',
    yawDeltaDegrees: 0,
    pitchDeltaDegrees: 0,
    targetOffsetGu: Object.freeze([0, 0, 0]),
    distanceScale: 1,
  }),
  desk: Object.freeze({
    id: 'desk',
    label: 'Desk focus',
    strategy: 'camera-policy',
    // Keep the accepted bedroom-side family; just bias the composition toward
    // the desk zone and move in slightly.
    yawDeltaDegrees: 5,
    pitchDeltaDegrees: -1,
    targetOffsetGu: Object.freeze([-95, -105, 12]),
    distanceScale: 0.94,
  }),
  living: Object.freeze({
    id: 'living',
    label: 'Living media focus',
    strategy: 'tv-couch-axis',
    tvId: 'living.tv',
    couchId: 'living.couch',
    // Preview-only composition distances. XY direction comes from the accepted
    // TV/couch footprints. Keep enough distance and height to preserve the
    // living-room relationship instead of collapsing into a TV close-up.
    eyeBeyondCouchGu: 760,
    targetTowardCouchGu: 230,
    eyeZGu: 690,
    targetZGu: 132,
  }),
})

export const DEFAULT_CONTEXT_CAMERA_POSE = 'rest'

export function resolveContextCameraPose(stateId = DEFAULT_CONTEXT_CAMERA_POSE) {
  return CONTEXT_CAMERA_POSES[stateId] ?? CONTEXT_CAMERA_POSES[DEFAULT_CONTEXT_CAMERA_POSE]
}

export function cameraPolicyForPose(baseCameraPolicy, pose) {
  if (pose.strategy !== 'camera-policy') {
    throw new TypeError(`Camera pose ${pose.id} does not derive from Camera v2 policy`)
  }
  const [baseX, baseY, baseZ] = baseCameraPolicy.target_gu.map(Number)
  const [dx, dy, dz] = pose.targetOffsetGu
  return {
    ...baseCameraPolicy,
    yaw_degrees_right: Number(baseCameraPolicy.yaw_degrees_right) + pose.yawDeltaDegrees,
    pitch_degrees_down: Number(baseCameraPolicy.pitch_degrees_down) + pose.pitchDeltaDegrees,
    target_gu: [baseX + dx, baseY + dy, baseZ + dz],
  }
}
