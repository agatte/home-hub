export const CONTEXT_CAMERA_POSES = Object.freeze({
  rest: Object.freeze({
    id: 'rest',
    label: 'Whole apartment',
    yawDeltaDegrees: 0,
    pitchDeltaDegrees: 0,
    targetOffsetGu: Object.freeze([0, 0, 0]),
    distanceScale: 1,
  }),
  desk: Object.freeze({
    id: 'desk',
    label: 'Desk focus',
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
    // Cross to the TV-facing side of the accepted hero family so the physical
    // display face becomes readable. This is a bounded contextual pose, not a
    // new geometry/camera authority.
    yawDeltaDegrees: -46,
    pitchDeltaDegrees: -2,
    targetOffsetGu: Object.freeze([125, -165, 8]),
    distanceScale: 0.92,
  }),
})

export const DEFAULT_CONTEXT_CAMERA_POSE = 'rest'

export function resolveContextCameraPose(stateId = DEFAULT_CONTEXT_CAMERA_POSE) {
  return CONTEXT_CAMERA_POSES[stateId] ?? CONTEXT_CAMERA_POSES[DEFAULT_CONTEXT_CAMERA_POSE]
}

export function cameraPolicyForPose(baseCameraPolicy, pose) {
  const [baseX, baseY, baseZ] = baseCameraPolicy.target_gu.map(Number)
  const [dx, dy, dz] = pose.targetOffsetGu
  return {
    ...baseCameraPolicy,
    yaw_degrees_right: Number(baseCameraPolicy.yaw_degrees_right) + pose.yawDeltaDegrees,
    pitch_degrees_down: Number(baseCameraPolicy.pitch_degrees_down) + pose.pitchDeltaDegrees,
    target_gu: [baseX + dx, baseY + dy, baseZ + dz],
  }
}
