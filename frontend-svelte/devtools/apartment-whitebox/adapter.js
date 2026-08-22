/**
 * GeometrySceneV1 -> local inspector data adapter.
 *
 * Exact rational GU strings remain untouched in GeometryScene. This is the
 * sole conversion boundary where the browser turns them into JavaScript
 * Numbers for Three.js buffers and camera state.
 */

export const INSPECTION_VERTICALS = Object.freeze({
  // Presentation-only review controls. They are deliberately not GeometryScene
  // authority and can be revised after the first visual inspection.
  bedroomSolidBaseGu: 92,
  bedroomUpperOpacity: 0.34,
})

export function parseRational(token) {
  if (typeof token !== 'string' || !/^-?\d+\/\d+$/.test(token)) {
    throw new TypeError(`Expected a reduced rational GU token, received ${String(token)}`)
  }
  const [numeratorToken, denominatorToken] = token.split('/')
  const numerator = BigInt(numeratorToken)
  const denominator = BigInt(denominatorToken)
  if (denominator <= 0n) {
    throw new RangeError(`Rational GU denominator must be positive: ${token}`)
  }
  // The source remains exact through GeometryScene. IEEE-754 conversion happens
  // here, once, because Three.js buffer attributes are JavaScript Numbers.
  const value = Number(numerator) / Number(denominator)
  if (!Number.isFinite(value)) throw new RangeError(`Rational GU token is outside renderer range: ${token}`)
  return value
}

export function pointToWorld(point) {
  return { x: parseRational(point[0]), y: parseRational(point[1]) }
}

function ringToWorld(ring) {
  return ring.map(pointToWorld)
}

function numberToken(token) {
  return parseRational(token)
}

function rectangleToWorld(rectangle) {
  return Object.fromEntries(Object.entries(rectangle).map(([key, value]) => [key, numberToken(value)]))
}

function faceIndex(volumes) {
  return new Map(volumes.flatMap((volume) => volume.faces.map((face) => [face.id, { ...face, wallId: volume.id }])))
}

function pairedFace(volume, hostFaceId) {
  return volume.faces.find((face) => face.id !== hostFaceId) ?? null
}

function isNonDegenerateFootprint(points) {
  let twiceArea = 0
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index]
    const next = points[(index + 1) % points.length]
    twiceArea += current.x * next.y - next.x * current.y
  }
  return Math.abs(twiceArea) > 0.000001
}

function parameterOnBearing(point, bearing) {
  const [start, end] = bearing.map(pointToWorld)
  const dx = end.x - start.x
  const dy = end.y - start.y
  const lengthSquared = dx * dx + dy * dy
  if (lengthSquared === 0) throw new Error('GeometryScene face has a zero-length bearing line')
  return ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared
}

function interpolateBearing(bearing, parameter) {
  const [start, end] = bearing.map(pointToWorld)
  return {
    x: start.x + (end.x - start.x) * parameter,
    y: start.y + (end.y - start.y) * parameter,
  }
}

function openingFootprint(opening, hostFace, oppositeFace) {
  if (!oppositeFace) return null
  const [start, end] = opening.segment_gu.map(pointToWorld)
  const oppositeStart = interpolateBearing(oppositeFace.bearing_line_gu, parameterOnBearing(start, hostFace.bearing_line_gu))
  const oppositeEnd = interpolateBearing(oppositeFace.bearing_line_gu, parameterOnBearing(end, hostFace.bearing_line_gu))
  const footprint = [start, end, oppositeEnd, oppositeStart]
  return isNonDegenerateFootprint(footprint) ? footprint : null
}

function selectorBounds(face, oppositeFace = null) {
  const points = [
    ...face.bearing_line_gu.map(pointToWorld),
    ...(oppositeFace ? oppositeFace.bearing_line_gu.map(pointToWorld) : []),
  ]
  return {
    minX: Math.min(...points.map((point) => point.x)),
    maxX: Math.max(...points.map((point) => point.x)),
    minY: Math.min(...points.map((point) => point.y)),
    maxY: Math.max(...points.map((point) => point.y)),
  }
}

function presentationById(treatments, id) {
  const treatment = treatments.find((item) => item.id === id)
  if (!treatment) throw new Error(`GeometryScene is missing required visibility treatment ${id}`)
  return treatment
}

function resolvedCutawayTarget(volumes, faces, wallId, faceId) {
  const wall = volumes.get(wallId)
  const face = faces.get(faceId)
  if (!wall || !face || face.wallId !== wall.id) {
    throw new Error(`Cutaway target ${wallId}/${faceId} is not an accepted stable semantic wall/face pair`)
  }
  return { wallId: wall.id, faceId: face.id, bounds: selectorBounds(face, pairedFace(wall, face.id)) }
}

function cutawayCandidates(volumes, faces, legacy) {
  const legacyTargets = [resolvedCutawayTarget(
    volumes, faces,
    'wall_volume.exterior.south_entry',
    'wall_face.exterior.south_entry.exterior_south',
  )]
  const acceptedTargets = legacy.selector.wall_ids.map((wallId, index) =>
    resolvedCutawayTarget(volumes, faces, wallId, legacy.selector.face_ids[index]))
  const northTargets = [
    resolvedCutawayTarget(
      volumes, faces,
      'wall_volume.exterior.bedroom_north',
      'wall_face.exterior.bedroom_north.exterior_north',
    ),
    resolvedCutawayTarget(
      volumes, faces,
      'wall_volume.living.balcony_north',
      'wall_face.living.balcony_north.balcony_north',
    ),
  ]
  return [
    {
      id: 'legacy_b', label: 'Legacy Cutaway B comparison', available: true,
      targets: legacyTargets,
      classification: 'provisional inspection cutaway — not accepted authority',
    },
    {
      id: 'accepted_north', label: 'Accepted bedroom-side north cutaway', available: true,
      targets: acceptedTargets,
      classification: 'accepted selector / provisional lip parameter',
    },
    {
      id: 'bedroom_north_west', label: 'Bedroom-side north + west cutaway', available: false,
      targets: northTargets,
      missingStableSelector: 'No accepted stable semantic wall-volume/face pair identifies the west exterior shell.',
      classification: 'debug comparison — not accepted authority',
    },
    {
      id: 'none', label: 'No cutaway', available: true, targets: [],
      classification: 'provisional inspection cutaway — not accepted authority',
    },
  ]
}

export function horizontalFovToVertical(horizontalDegrees, aspect) {
  const horizontalRadians = horizontalDegrees * Math.PI / 180
  return 2 * Math.atan(Math.tan(horizontalRadians / 2) / aspect) * 180 / Math.PI
}

export function geometryBounds(data) {
  const points = [
    ...data.slabs.flatMap((slab) => slab.ring.map((point) => ({ ...point, zMin: slab.zMin, zMax: slab.zMax }))),
    ...data.walls.flatMap((wall) => [wall.outer, ...wall.holes]
      .flatMap((ring) => ring.map((point) => ({ ...point, zMin: wall.zMin, zMax: wall.zMax })))),
  ]
  if (points.length === 0) throw new Error('Cannot frame an empty GeometryScene')
  return {
    minX: Math.min(...points.map((point) => point.x)),
    maxX: Math.max(...points.map((point) => point.x)),
    minY: Math.min(...points.map((point) => point.y)),
    maxY: Math.max(...points.map((point) => point.y)),
    minZ: Math.min(...points.map((point) => point.zMin)),
    maxZ: Math.max(...points.map((point) => point.zMax)),
  }
}

function boundsCorners(bounds) {
  return [bounds.minX, bounds.maxX].flatMap((x) =>
    [bounds.minY, bounds.maxY].flatMap((y) =>
      [bounds.minZ, bounds.maxZ].map((z) => ({ x, y, z }))))
}

function dot(a, b) {
  return a.x * b.x + a.y * b.y + a.z * b.z
}

export function perspectiveCandidate(bounds, aspect, cameraPolicy) {
  const margin = Number(cameraPolicy.fit_policy.margin)
  if (!(aspect > 0) || !(margin >= 1)) throw new RangeError('Camera aspect and margin must be positive')
  const yaw = Number(cameraPolicy.yaw_degrees_right) * Math.PI / 180
  const pitch = Number(cameraPolicy.pitch_degrees_down) * Math.PI / 180
  const horizontalFovDegrees = Number(cameraPolicy.horizontal_fov_degrees)
  const [x, y, z] = cameraPolicy.target_gu.map(Number)
  const target = { x, y, z }
  // Upper-left / bedroom-side counterpart to the legacy entry-side eye.
  // In plan coordinates, -y is canonical plan-up and -x is plan-left.
  const eyeDirection = {
    x: -Math.sin(yaw) * Math.cos(pitch),
    y: -Math.cos(yaw) * Math.cos(pitch),
    z: Math.sin(pitch),
  }
  const forward = { x: -eyeDirection.x, y: -eyeDirection.y, z: -eyeDirection.z }
  const rightLength = Math.hypot(forward.y, -forward.x)
  const right = { x: forward.y / rightLength, y: -forward.x / rightLength, z: 0 }
  const up = {
    x: right.y * forward.z,
    y: -right.x * forward.z,
    z: right.x * forward.y - right.y * forward.x,
  }
  const tanHorizontal = Math.tan(horizontalFovDegrees * Math.PI / 360) / margin
  const verticalFovDegrees = horizontalFovToVertical(horizontalFovDegrees, aspect)
  const tanVertical = Math.tan(verticalFovDegrees * Math.PI / 360) / margin
  let distance = 0
  for (const corner of boundsCorners(bounds)) {
    const relative = { x: corner.x - target.x, y: corner.y - target.y, z: corner.z - target.z }
    const depthOffset = dot(relative, forward)
    distance = Math.max(
      distance,
      Math.abs(dot(relative, right)) / tanHorizontal - depthOffset,
      Math.abs(dot(relative, up)) / tanVertical - depthOffset,
      1 - depthOffset,
    )
  }
  const eye = {
    x: target.x + eyeDirection.x * distance,
    y: target.y + eyeDirection.y * distance,
    z: target.z + eyeDirection.z * distance,
  }
  return { eye, target, distance, forward, right, up, horizontalFovDegrees, verticalFovDegrees, margin }
}

export function projectPerspectivePoint(point, view) {
  const relative = { x: point.x - view.eye.x, y: point.y - view.eye.y, z: point.z - view.eye.z }
  const depth = dot(relative, view.forward)
  return {
    x: dot(relative, view.right) / (depth * Math.tan(view.horizontalFovDegrees * Math.PI / 360)),
    y: dot(relative, view.up) / (depth * Math.tan(view.verticalFovDegrees * Math.PI / 360)),
    depth,
  }
}

export function perspectiveContainsBounds(bounds, view) {
  return boundsCorners(bounds).every((corner) => {
    const projected = projectPerspectivePoint(corner, view)
    return projected.depth > 0 && Math.abs(projected.x) <= 1 && Math.abs(projected.y) <= 1
  })
}

export function topDownTruthView(bounds, aspect, margin = 1.1) {
  if (!(aspect > 0) || !(margin >= 1)) throw new RangeError('Camera aspect and margin must be positive')
  const target = {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
    z: bounds.minZ,
  }
  const width = bounds.maxX - bounds.minX
  const height = bounds.maxY - bounds.minY
  const halfHeight = Math.max(height / 2, width / (2 * aspect)) * margin
  return {
    eye: { x: target.x, y: target.y, z: bounds.maxZ + Math.max(width, height) },
    target,
    // A Z-up camera looking down needs +Y camera-up for screen-right to be
    // +plan-X.  The named presentation transform below then maps plan-Y-down
    // to screen-down without changing GeometryScene coordinates.
    cameraUp: { x: 0, y: 1, z: 0 },
    presentationTransform: {
      kind: 'truth_view_plan_y_reflection_about_target',
      status: 'presentation_only',
      scale: { x: 1, y: -1, z: 1 },
      pivotY: target.y,
    },
    halfWidth: halfHeight * aspect,
    halfHeight,
    margin,
  }
}

export function topDownCameraBasis(cameraUp) {
  const forward = { x: 0, y: 0, z: -1 }
  // Three's camera screen-right is forward × camera-up for this look-down
  // orientation.  Keeping this explicit prevents a source-coordinate-only
  // test from missing a displayed reflection again.
  const screenRight = {
      x: forward.y * cameraUp.z - forward.z * cameraUp.y,
      y: forward.z * cameraUp.x - forward.x * cameraUp.z,
      z: forward.x * cameraUp.y - forward.y * cameraUp.x,
    }
  for (const axis of Object.keys(screenRight)) {
    if (Object.is(screenRight[axis], -0)) screenRight[axis] = 0
  }
  return {
    screenRight,
    screenUp: cameraUp,
  }
}

export function projectTopDownPoint(point, view) {
  // This is the final display projection used by the production truth view:
  // first reflect plan-Y about the target as a presentation-only transform,
  // then project through the +Y-up orthographic camera.
  return {
    x: (point.x - view.target.x) / view.halfWidth,
    y: (view.target.y - point.y) / view.halfHeight,
  }
}

export function adaptGeometryScene(scene) {
  if (scene.schema !== 'homehub.apartment-geometry-scene.v1') {
    throw new Error(`Unsupported GeometryScene schema: ${scene.schema}`)
  }
  const volumes = new Map(scene.semantic_wall_volumes.map((volume) => [volume.id, volume]))
  const faces = faceIndex(scene.semantic_wall_volumes)
  const cutaway = presentationById(scene.visibility_treatments, 'visibility.global_cutaway')
  const bedroom = presentationById(scene.visibility_treatments, 'visibility.bedroom_front_wall')
  const cutawayLipGu = Number(cutaway.parameters.inspection_lip_height_gu)
  if (!Number.isFinite(cutawayLipGu) || cutaway.parameters.inspection_lip_status !== 'provisional') {
    throw new Error('Accepted cutaway must provide a provisional numeric inspection lip')
  }
  const cutawayWall = volumes.get(cutaway.selector.wall_ids[0])
  const cutawayFace = faces.get(cutaway.selector.face_ids[0])
  const bedroomWall = volumes.get(bedroom.selector.wall_id)
  const bedroomFace = faces.get(bedroom.selector.face_id)
  if (!cutawayWall || !cutawayFace || cutawayFace.wallId !== cutawayWall.id) {
    throw new Error('Accepted cutaway does not resolve to its named GeometryScene wall/face')
  }
  if (!bedroomWall || !bedroomFace || bedroomFace.wallId !== bedroomWall.id) {
    throw new Error('Bedroom treatment C does not resolve to its named GeometryScene wall/face')
  }

  const openings = scene.openings.map((opening) => {
    const hostFace = faces.get(opening.host_face_id)
    const parentWall = volumes.get(opening.parent_wall_id)
    if (!hostFace || !parentWall || hostFace.wallId !== parentWall.id) {
      throw new Error(`Opening ${opening.id} cannot resolve its named host wall/face`)
    }
    const oppositeFace = pairedFace(parentWall, hostFace.id)
    const footprint = opening.kind === 'window'
      ? openingFootprint(opening, hostFace, oppositeFace)
      : null
    const vertical = {
      min: numberToken(opening.vertical.z_min_gu),
      max: numberToken(opening.vertical.z_max_gu),
    }
    return {
      id: opening.id,
      sourceApertureId: opening.source_aperture_id,
      kind: opening.kind,
      segment: opening.segment_gu.map(pointToWorld),
      hostWallId: parentWall.id,
      hostFaceId: hostFace.id,
      void: vertical,
      // Registered plan gaps already make the aperture void. For windows, the
      // accepted non-degenerate host/opposite faces let the renderer restore
      // only the required sill and lintel solids around that void.
      closureFootprint: footprint,
      solidRanges: opening.kind === 'window' && footprint
        ? [{ min: 0, max: vertical.min }, { min: vertical.max, max: null }]
        : [],
      inspection: {
        renderObjectType: 'registered opening',
        geometrySceneObjectId: opening.id,
        sourceApertureId: opening.source_aperture_id,
        semanticWallVolumeId: parentWall.id,
        semanticFaceId: hostFace.id,
        classification: 'authoritative accepted aperture XY; provisional registry vertical descriptor',
      },
    }
  })

  const wallTop = numberToken(scene.z_policy.wall_body.z_max_gu)
  for (const opening of openings) {
    opening.solidRanges = opening.solidRanges
      .map((range) => ({ ...range, max: range.max ?? wallTop }))
      .filter((range) => range.max > range.min)
  }

  const adapted = {
    fingerprint: scene.fingerprint,
    slabs: scene.floor_slabs.map((slab) => ({
      id: slab.id,
      kind: slab.kind,
      ring: ringToWorld(slab.footprint_ring_gu),
      zMin: numberToken(slab.z_min_gu),
      zMax: numberToken(slab.z_max_gu),
    })),
    walls: scene.wall_extrusions.map((wall) => ({
      id: wall.id,
      outer: ringToWorld(wall.footprint_gu.outer),
      holes: wall.footprint_gu.holes.map(ringToWorld),
      zMin: numberToken(wall.z_min_gu),
      zMax: numberToken(wall.z_max_gu),
      inspection: {
        renderObjectType: 'wall extrusion',
        geometrySceneObjectId: wall.id,
        sourcePolygonId: wall.source_polygon_id,
        sourceContourSegments: [...new Set(wall.polygon_provenance.outer.flatMap((edge) => edge.source_segments))],
        semanticWallVolumeId: null,
        semanticFaceId: null,
        classification: 'authoritative accepted XY wall footprint; provisional whitebox Z',
      },
    })),
    openings,
    rooms: scene.inspection_annotations.rooms.map((room) => ({
      ...room,
      position: pointToWorld(room.label_gu),
      classification: 'accepted approximate XY label position / provisional debug overlay',
    })),
    fixtureDebugAids: scene.inspection_annotations.objects
      .filter((item) => ['bath.shower', 'bath.vanity', 'bath.toilet'].includes(item.id))
      .map((item) => ({
        ...item,
        rect: rectangleToWorld(item.rect_gu),
        classification: 'accepted approximate XY / provisional 3D debug aid',
      })),
    camera: {
      ...scene.camera.camera,
      legacyComparison: scene.camera.legacy_comparison,
    },
    presentation: {
      cutaway: {
        // Named IDs are the only selector. There is intentionally no camera
        // position/depth predicate in this adapter.
        wallId: cutawayWall.id,
        faceId: cutawayFace.id,
        bounds: selectorBounds(cutawayFace, pairedFace(cutawayWall, cutawayFace.id)),
        lipHeightGu: cutawayLipGu,
        lipStatus: cutaway.parameters.inspection_lip_status,
      },
      bedroom: {
        wallId: bedroomWall.id,
        faceId: bedroomFace.id,
        // The selected face is exact even where the accepted semantic pair is
        // coincident; the renderer changes only that face's upper surface.
        faceBounds: selectorBounds(bedroomFace),
        faceNormal: bedroomFace.plan_normal,
        solidBaseHeightGu: INSPECTION_VERTICALS.bedroomSolidBaseGu,
        upperOpacity: INSPECTION_VERTICALS.bedroomUpperOpacity,
      },
    },
  }
  adapted.presentation.cutawayCandidates = cutawayCandidates(volumes, faces, cutaway)
  adapted.bounds = geometryBounds(adapted)
  return adapted
}
