import physicalWorld from '../../../docs/dashboard/apartment_canvas/physical_world_v1.json'

export const physicalWorldV1 = Object.freeze(physicalWorld)

function objectById(id) {
  const object = physicalWorldV1.objects.find((item) => item.id === id)
  if (!object) throw new Error(`Physical World v1 is missing ${id}`)
  return object
}

export function inchesToGu(inches, calibrationId = 'apartment_physical_v1') {
  const calibration = physicalWorldV1.calibrations[calibrationId]
  if (!calibration || calibration.status !== 'provisional_apartment_wide') {
    throw new Error(`Physical World v1 cannot resolve apartment calibration ${calibrationId}`)
  }
  if (!Number.isFinite(inches)) throw new TypeError(`Physical inches must be finite, received ${inches}`)
  return inches * calibration.gu_per_in
}

function dimensionsGu(object) {
  const dimensions = {}
  for (const [axis, inches] of Object.entries(object.physical_dimensions_in)) {
    dimensions[axis] = inchesToGu(inches, object.calibration_ref)
  }
  return dimensions
}

function rectangle(x, y, w, h) {
  return { x, y, w, h, maxX: x + w, maxY: y + h }
}

export function resolveBedroomPhysicalWorld() {
  const bed = objectById('bedroom.braya_bed')
  const main = objectById('bedroom.burgener_main')
  const returnDesk = objectById('bedroom.burgener_return')
  const windowSill = physicalWorldV1.architectural_features.find((item) => item.id === 'bedroom.window_sill')
  if (!windowSill) throw new Error('Physical World v1 is missing bedroom.window_sill')
  const bedDimensions = dimensionsGu(bed)
  const mainDimensions = dimensionsGu(main)
  const returnDimensions = dimensionsGu(returnDesk)

  const mainRect = rectangle(
    main.preview_placement.x_start_gu,
    main.preview_placement.rear_edge_y_gu - mainDimensions.deep,
    mainDimensions.long,
    mainDimensions.deep,
  )
  const returnRect = rectangle(
    returnDesk.preview_placement.x_start_gu,
    mainRect.y - returnDimensions.long,
    returnDimensions.deep,
    returnDimensions.long,
  )
  const bedRect = rectangle(
    bed.preview_placement.origin_gu.x,
    bed.preview_placement.origin_gu.y,
    bedDimensions.long,
    bedDimensions.wide,
  )
  const sillPreview = windowSill.preview_placement
  const sillRect = rectangle(
    sillPreview.host_window_span_gu.x_min - sillPreview.side_overhang_each_gu,
    sillPreview.host_window_span_gu.window_wall_plane_y,
    sillPreview.host_window_span_gu.x_max - sillPreview.host_window_span_gu.x_min + sillPreview.side_overhang_each_gu * 2,
    sillPreview.projection_depth_gu,
  )
  const attachment = physicalWorldV1.attachments.find((item) => item.id === 'bedroom.projector_on_return')
  const projectorFootprint = { w: 21.4, h: 24.4, status: 'provisional_visual_footprint' }
  const projectorCenter = {
    x: returnRect.x + returnRect.w * attachment.placement.u,
    y: returnRect.y + projectorFootprint.h / 2 + (returnRect.h - projectorFootprint.h) * attachment.placement.v,
  }
  const projectorRect = rectangle(
    projectorCenter.x - projectorFootprint.w / 2,
    projectorCenter.y - projectorFootprint.h / 2,
    projectorFootprint.w,
    projectorFootprint.h,
  )

  return Object.freeze({
    calibration: physicalWorldV1.calibrations.apartment_physical_v1,
    objects: Object.freeze({
      bed: Object.freeze({ ...bed, dimensions_gu: Object.freeze(bedDimensions), plan_bounds_gu: Object.freeze(bedRect) }),
      main: Object.freeze({ ...main, dimensions_gu: Object.freeze(mainDimensions), plan_bounds_gu: Object.freeze(mainRect) }),
      return: Object.freeze({ ...returnDesk, dimensions_gu: Object.freeze(returnDimensions), plan_bounds_gu: Object.freeze(returnRect) }),
      projector: Object.freeze({ ...attachment, plan_bounds_gu: Object.freeze(projectorRect), visual_footprint: Object.freeze(projectorFootprint) }),
    }),
    architecture: Object.freeze({
      windowSill: Object.freeze({ ...windowSill, plan_bounds_gu: Object.freeze(sillRect) }),
    }),
    compatibility: physicalWorldV1.compatibility_preview,
  })
}

export function resolveLivingRoomSofaPhysicalWorld() {
  const sofa = objectById('living.sofa')
  const wall = physicalWorldV1.architectural_features.find((item) => item.id === 'living.east_back_wall.finished_room_side_plane')
  if (!wall) throw new Error('Physical World v1 is missing living.east_back_wall.finished_room_side_plane')
  const dimensions = dimensionsGu(sofa)
  const placement = sofa.preview_placement
  const rearEdge = placement.rear_edge_x_gu
  const planBounds = rectangle(
    rearEdge - dimensions.deep,
    placement.long_axis_start_y_gu,
    dimensions.deep,
    dimensions.long,
  )

  return Object.freeze({
    calibration: physicalWorldV1.calibrations.apartment_physical_v1,
    sofa: Object.freeze({
      ...sofa,
      dimensions_gu: Object.freeze(dimensions),
      plan_bounds_gu: Object.freeze(planBounds),
      rear_edge_x_gu: rearEdge,
      seat_height_gu: inchesToGu(sofa.physical_dimensions_in.seat_high, sofa.calibration_ref),
    }),
    architecture: Object.freeze({
      finishedBackWall: Object.freeze({ ...wall, room_side_plane_x_gu: wall.preview_placement.room_side_plane_x_gu }),
    }),
  })
}

export function compatibilityFootprint(id, fallback) {
  return physicalWorldV1.compatibility_preview.objects[id]?.rect_gu ?? fallback
}
