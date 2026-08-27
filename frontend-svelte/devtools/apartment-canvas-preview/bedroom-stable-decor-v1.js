import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'
import { resolveBedroomWorkstationAccessories } from './workstation-accessories-v1.js'

function rectangle(x, y, w, h) {
  return Object.freeze({ x, y, w, h, maxX: x + w, maxY: y + h })
}

// Photo-supported secondary objects only. These placements deliberately derive
// from accepted desk/projector envelopes without changing any of them.
export function resolveBedroomStableDecor(physical = resolveBedroomPhysicalWorld()) {
  const main = physical.objects.main.plan_bounds_gu
  const projector = physical.objects.projector.plan_bounds_gu
  const rightLamp = resolveBedroomWorkstationAccessories(physical).rightLamp

  return Object.freeze({
    status: 'provisional_review_required',
    source: 'real_room_photographs+provisional_preview_inference',
    floralPrint: Object.freeze({
      relationship: 'freestanding_directly_forward_of_main_right_lamp_base',
      // The print is immediately in front of the clear lamp base in both desk
      // photos, so it shares that diagonal visual family rather than joining
      // the separate projector/return composition.
      bounds: rectangle(rightLamp.bounds.x + rightLamp.bounds.w * 0.56 - 7.75, rightLamp.bounds.y - 8.2, 15.5, 1.1),
      height_gu: 22,
      face_direction: 'toward_main_desk_front',
      yaw_radians: 0,
      lean_radians: -0.1,
    }),
    projectorCable: Object.freeze({
      relationship: 'short_rear_projector_power_video_lead',
      start: Object.freeze({ x: projector.x + projector.w * 0.27, y: projector.maxY - 0.5 }),
      bend: Object.freeze({ x: projector.x + projector.w * 0.12, y: projector.maxY + 3.4 }),
      end: Object.freeze({ x: projector.x + projector.w * 0.04, y: projector.maxY + 7.6 }),
    }),
    deskCable: Object.freeze({
      relationship: 'single_under_desk_power_drop_below_main_rear_edge',
      start: Object.freeze({ x: main.x + main.w * 0.57, y: main.maxY - 1.1 }),
      end: Object.freeze({ x: main.x + main.w * 0.57, y: main.maxY - 4.2 }),
    }),
  })
}
