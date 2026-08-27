import { describe, expect, it } from 'vitest'
import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'
import { resolveBedroomStableDecor } from './bedroom-stable-decor-v1.js'
import { resolveBedroomWorkstationAccessories } from './workstation-accessories-v1.js'

describe('Bedroom stable decor v1', () => {
  it('keeps the freestanding print immediately forward of the right lamp with its face toward the desk', () => {
    const physical = resolveBedroomPhysicalWorld()
    const decor = resolveBedroomStableDecor(physical)
    const projector = physical.objects.projector.plan_bounds_gu
    const rightLamp = resolveBedroomWorkstationAccessories(physical).rightLamp

    expect(decor.status).toBe('provisional_review_required')
    expect(decor.floralPrint.relationship).toBe('freestanding_directly_forward_of_main_right_lamp_base')
    expect(decor.floralPrint.bounds.maxY).toBeLessThan(rightLamp.bounds.y)
    expect(decor.floralPrint.face_direction).toBe('toward_main_desk_front')
    expect(decor.floralPrint.yaw_radians).toBe(0)
    expect(decor.floralPrint.lean_radians).toBeLessThan(0)
    expect(decor).not.toHaveProperty('books')
    expect(physical.objects.projector.plan_bounds_gu).toEqual(projector)
  })

  it('keeps the projector lead local to the projector, without a frame-to-projector line', () => {
    const decor = resolveBedroomStableDecor()
    expect(decor.projectorCable.relationship).toBe('short_rear_projector_power_video_lead')
    expect(decor.projectorCable.end.y - decor.projectorCable.start.y).toBeLessThan(10)
    expect(decor.projectorCable.end.y).toBeLessThan(decor.floralPrint.bounds.y)
    expect(decor.deskCable.relationship).toBe('single_under_desk_power_drop_below_main_rear_edge')
    expect(decor).not.toHaveProperty('powerBrick')
    expect(decor).not.toHaveProperty('wallConnection')
  })
})
