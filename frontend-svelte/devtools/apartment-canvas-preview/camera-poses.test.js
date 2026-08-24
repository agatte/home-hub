import { describe, expect, it } from 'vitest'
import {
  cameraPolicyForPose,
  DEFAULT_CONTEXT_CAMERA_POSE,
  resolveContextCameraPose,
} from './camera-poses.js'

const BASE = Object.freeze({
  yaw_degrees_right: 20,
  pitch_degrees_down: 36,
  target_gu: [499.6, 633.85, 118],
})

describe('Apartment Canvas contextual camera poses', () => {
  it('defaults to the accepted whole-apartment pose', () => {
    expect(resolveContextCameraPose('unknown').id).toBe(DEFAULT_CONTEXT_CAMERA_POSE)
    expect(resolveContextCameraPose('rest').distanceScale).toBe(1)
  })

  it('derives desk camera policy without mutating the accepted base policy', () => {
    const pose = resolveContextCameraPose('desk')
    const derived = cameraPolicyForPose(BASE, pose)

    expect(derived.yaw_degrees_right).toBe(25)
    expect(derived.pitch_degrees_down).toBe(35)
    expect(derived.target_gu).toEqual([404.6, 528.85, 130])
    expect(BASE.target_gu).toEqual([499.6, 633.85, 118])
  })

  it('crosses to the TV-facing side for living media', () => {
    const pose = resolveContextCameraPose('living')
    const derived = cameraPolicyForPose(BASE, pose)

    expect(derived.yaw_degrees_right).toBe(-26)
    expect(derived.pitch_degrees_down).toBe(34)
    expect(derived.target_gu).toEqual([624.6, 468.85, 126])
  })
})
