import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'

function rectangle(x, y, w, h) {
  return Object.freeze({ x, y, w, h, maxX: x + w, maxY: y + h })
}

function fromMain(main, { u, rearInset, w, h }) {
  return rectangle(
    main.x + main.w * u - w / 2,
    main.maxY - rearInset - h / 2,
    w,
    h,
  )
}

// Camera v2's accepted reflection reverses raw x on presentation. Keep the
// desk-local anchors in the photo's left/open -> right/return convention, and
// perform that one conversion at the renderer boundary.
function fromMainDeskLocal(main, { leftOpenU, rearInset, w, h }) {
  return fromMain(main, { u: 1 - leftOpenU, rearInset, w, h })
}

// These are explicitly provisional renderer anchors. Their relationships are
// photo/user-confirmed; their numeric offsets are not physical measurements.
export function resolveBedroomWorkstationAccessories(physical = resolveBedroomPhysicalWorld()) {
  const main = physical.objects.main.plan_bounds_gu
  const returnDesk = physical.objects.return.plan_bounds_gu
  const chairWidth = 63.47
  const chairDepth = 66.72

  return Object.freeze({
    status: 'provisional_review_required',
    source: 'real_room_photographs+explicit_user_confirmation+provisional_preview_inference',
    pc: Object.freeze({
      relationship: 'under_main_return_junction_side',
      bounds: rectangle(returnDesk.maxX - 28.5, main.y + 3.5, 31, 57),
      height_gu: 72,
      status: 'provisional_review_required',
    }),
    monitor: Object.freeze({
      relationship: 'main_rear_edge_centered_working_zone',
      local_anchor: 'main_center_rear',
      bounds: fromMainDeskLocal(main, { leftOpenU: 0.5, rearInset: 10, w: 63.47, h: 14.65 }),
      status: 'provisional_review_required',
    }),
    microphone: Object.freeze({
      relationship: 'main_monitor_right_slightly_roomward',
      local_anchor: 'monitor_right_clearance_forward',
      bounds: fromMainDeskLocal(main, { leftOpenU: 0.69, rearInset: 18, w: 11.39, h: 11.39 }),
      status: 'provisional_review_required',
    }),
    // The accepted reflected presentation maps raw +x to the user's left.
    leftLamp: Object.freeze({
      relationship: 'main_rear_open_end_opposite_return',
      local_anchor: 'main_rear_left_open_end',
      bounds: fromMainDeskLocal(main, { leftOpenU: 0.12, rearInset: 10, w: 17.9, h: 17.9 }),
      status: 'provisional_review_required',
    }),
    rightLamp: Object.freeze({
      relationship: 'main_rear_right_corner_diagonal_toward_chair',
      local_anchor: 'main_rear_right_corner',
      // Small visual reconciliation: the base stays wholly on the main top,
      // but now occupies the photographed rear-right corner rather than an
      // inboard approximation. Reflection is still handled at the boundary.
      local_left_open_u: 0.94,
      bounds: fromMainDeskLocal(main, { leftOpenU: 0.94, rearInset: 10, w: 22, h: 13 }),
      orientation: Object.freeze({
        base_long_axis: 'rear_right_to_front_center',
        stem_anchor: 'rear_right',
        shade_direction: 'inward_front_center',
      }),
      yaw_radians: -Math.PI / 4,
      stem_local_x_gu: -4,
      shade_local_x_gu: 7,
      status: 'provisional_review_required',
    }),
    headphones: Object.freeze({
      relationship: 'main_rear_open_side_behind_work_surface',
      // Kept on the same wood-side lane, just behind the bounded black mat.
      bounds: fromMain(main, { u: 0.76, rearInset: 11, w: 14.65, h: 14.65 }),
      status: 'provisional_review_required',
    }),
    alexa: Object.freeze({
      relationship: 'main_rear_left_of_fabric_lamp',
      local_anchor: 'left_of_left_lamp',
      bounds: fromMainDeskLocal(main, { leftOpenU: 0.06, rearInset: 10, w: 14.65, h: 14.65 }),
      status: 'provisional_review_required',
    }),
    chair: Object.freeze({
      relationship: 'main_front_centered_working_knee_span',
      bounds: rectangle(main.x + main.w * 0.5 - chairWidth / 2, main.y - 7.54 - chairDepth, chairWidth, chairDepth),
      status: 'provisional_review_required',
    }),
  })
}
