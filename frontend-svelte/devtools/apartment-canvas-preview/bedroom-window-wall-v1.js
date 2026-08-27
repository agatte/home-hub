export const BEDROOM_WINDOW_WALL_REALIZATION_V1 = Object.freeze({
  classification: 'presentation_only_recessed_glazing_with_flush_below_sill_wall',
  roomSideDirection: '+y',
  // Derived from the accepted solid bedroom north-wall boundary. It is kept
  // separate from the recessed registered window host/glazing plane.
  finishedRoomSideYGu: 65.91,
})

export function bedroomWindowWallClosureFootprint(opening) {
  if (!opening.sourceApertureId?.startsWith('bedroom_window_')) return opening.closureFootprint
  const [start, end] = opening.segment
  if (Math.abs(start.y - end.y) > 0.000001) throw new Error(`${opening.id} is not a horizontal bedroom window span`)
  if (BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu <= start.y) {
    throw new Error('Bedroom finished room-side wall must be beyond the recessed window host plane')
  }
  // Glazing remains at the registered host plane. This closure is the wall
  // thickness/reveal below and above it, with one visible finished face at the
  // accepted room-side wall plane—not a second overlay surface.
  return [
    start,
    end,
    { x: end.x, y: BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu },
    { x: start.x, y: BEDROOM_WINDOW_WALL_REALIZATION_V1.finishedRoomSideYGu },
  ]
}
