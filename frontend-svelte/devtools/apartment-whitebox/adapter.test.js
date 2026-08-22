import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import scene from './generated/geometry-scene.json'
import {
  adaptGeometryScene,
  horizontalFovToVertical,
  parseRational,
  perspectiveCandidate,
  perspectiveContainsBounds,
  projectTopDownPoint,
  topDownCameraBasis,
  topDownTruthView,
} from './adapter.js'

const data = adaptGeometryScene(scene)
const toolDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryDirectory = path.resolve(toolDirectory, '../../..')

describe('Apartment Canvas whitebox adapter', () => {
  it('converts every GeometryScene slab and wall extrusion into renderable geometry', () => {
    expect(data.slabs).toHaveLength(scene.floor_slabs.length)
    expect(data.walls).toHaveLength(scene.wall_extrusions.length)
    expect(data.slabs.map((slab) => slab.id)).toEqual(scene.floor_slabs.map((slab) => slab.id))
    expect(data.walls.map((wall) => wall.id)).toEqual(scene.wall_extrusions.map((wall) => wall.id))
    expect(data.walls.every((wall) => wall.outer.length >= 3 && wall.zMax > wall.zMin)).toBe(true)
  })

  it('represents every registered aperture as an opening realization', () => {
    expect(data.openings).toHaveLength(scene.openings.length)
    expect(data.openings.map((opening) => opening.sourceApertureId).sort()).toEqual(
      scene.openings.map((opening) => opening.source_aperture_id).sort(),
    )
    expect(data.openings.every((opening) => opening.void.max > opening.void.min)).toBe(true)
    expect(data.openings.filter((opening) => opening.kind === 'window').every(
      (opening) => opening.closureFootprint && opening.solidRanges.length === 2,
    )).toBe(true)
    expect(data.openings.filter((opening) => opening.kind === 'door').every(
      (opening) => opening.closureFootprint === null && opening.solidRanges.length === 0
        && !Object.hasOwn(opening, 'headerSurface'),
    )).toBe(true)
  })

  it('parses exact rational tokens deterministically at the renderer boundary', () => {
    expect(parseRational('330553295362083/6250000000000')).toBe(52.88852725793328)
    expect(parseRational('-4/1')).toBe(-4)
    expect(() => parseRational('52.5')).toThrow(TypeError)
    expect(() => parseRational('2/0')).toThrow(RangeError)
  })

  it('preserves the legacy camera separately with Z-up and horizontal FOV semantics', () => {
    expect(data.camera.target_gu).toEqual(scene.camera.camera.target_gu)
    expect(data.camera.horizontal_fov_degrees).toBe(scene.camera.camera.horizontal_fov_degrees)
    expect(horizontalFovToVertical(45, 16 / 9)).toBeCloseTo(26.231, 3)
  })

  it('uses an explicit presentation-only transform to make final truth-view screen axes canonical', () => {
    const view = topDownTruthView(data.bounds, 2)
    const topLeft = projectTopDownPoint({ x: data.bounds.minX, y: data.bounds.minY }, view)
    const bottomRight = projectTopDownPoint({ x: data.bounds.maxX, y: data.bounds.maxY }, view)

    expect(view.presentationTransform).toEqual({
      kind: 'truth_view_plan_y_reflection_about_target',
      status: 'presentation_only',
      scale: { x: 1, y: -1, z: 1 },
      pivotY: view.target.y,
    })
    expect(topDownCameraBasis(view.cameraUp)).toEqual({
      screenRight: { x: 1, y: 0, z: 0 },
      screenUp: { x: 0, y: 1, z: 0 },
    })
    expect(topLeft.x).toBeLessThan(0) // min-x remains plan-left
    expect(topLeft.y).toBeGreaterThan(0) // min-y remains plan-top
    expect(bottomRight.x).toBeGreaterThan(0)
    expect(bottomRight.y).toBeLessThan(0)
    expect(Math.abs(topLeft.x)).toBeLessThan(1)
    expect(Math.abs(topLeft.y)).toBeLessThan(1)
    expect(Math.abs(bottomRight.x)).toBeLessThan(1)
    expect(Math.abs(bottomRight.y)).toBeLessThan(1)
  })

  it('projects final production truth-view room labels into canonical screen orientation', () => {
    const view = topDownTruthView(data.bounds, 16 / 9)
    const screen = Object.fromEntries(data.rooms.map((room) => [room.id, projectTopDownPoint(room.position, view)]))
    expect(screen.bedroom.x).toBeLessThan(screen.balcony.x)
    expect(screen.bath.x).toBeLessThan(screen.living.x)
    expect(screen.kitchen.x).toBeGreaterThan(screen.entry.x)
    expect(projectTopDownPoint({ x: data.bounds.minX, y: view.target.y }, view).x).toBeLessThan(
      projectTopDownPoint({ x: data.bounds.maxX, y: view.target.y }, view).x,
    )
    expect(projectTopDownPoint({ x: view.target.x, y: data.bounds.minY }, view).y).toBeGreaterThan(
      projectTopDownPoint({ x: view.target.x, y: data.bounds.maxY }, view).y,
    )
  })

  it('keeps canonical balcony top/right and entry bottom landmarks in top-down truth', () => {
    const view = topDownTruthView(data.bounds, 2)
    const balcony = data.slabs.find((slab) => slab.kind === 'balcony_floor_slab')
    const balconyCenter = {
      x: (Math.min(...balcony.ring.map((point) => point.x)) + Math.max(...balcony.ring.map((point) => point.x))) / 2,
      y: (Math.min(...balcony.ring.map((point) => point.y)) + Math.max(...balcony.ring.map((point) => point.y))) / 2,
    }
    const frontDoor = data.openings.find((opening) => opening.sourceApertureId === 'front_door')
    const entryCenter = {
      x: (frontDoor.segment[0].x + frontDoor.segment[1].x) / 2,
      y: (frontDoor.segment[0].y + frontDoor.segment[1].y) / 2,
    }

    expect(projectTopDownPoint(balconyCenter, view)).toMatchObject({
      x: expect.any(Number), y: expect.any(Number),
    })
    expect(projectTopDownPoint(balconyCenter, view).x).toBeGreaterThan(0)
    expect(projectTopDownPoint(balconyCenter, view).y).toBeGreaterThan(0)
    expect(projectTopDownPoint(entryCenter, view).y).toBeLessThan(0)
  })

  it.each([0.5, 1, 16 / 9, 2])('fits every GeometryScene bounds corner at responsive aspect %s', (aspect) => {
    const candidate = perspectiveCandidate(data.bounds, aspect, data.camera)
    expect(candidate.eye.x).toBeLessThan(data.bounds.minX)
    expect(candidate.eye.y).toBeLessThan(data.bounds.minY)
    expect(candidate.eye.z).toBeGreaterThan(data.bounds.maxZ)
    const dx = candidate.eye.x - candidate.target.x
    const dy = candidate.eye.y - candidate.target.y
    const dz = candidate.eye.z - candidate.target.z
    expect(Math.atan2(Math.abs(dx), Math.abs(dy)) * 180 / Math.PI).toBeCloseTo(20, 8)
    expect(Math.atan2(dz, Math.hypot(dx, dy)) * 180 / Math.PI).toBeCloseTo(36, 8)
    expect(candidate.horizontalFovDegrees).toBe(45)
    expect(perspectiveContainsBounds(data.bounds, candidate)).toBe(true)
  })

  it('does not mutate any source-derived aperture XY while adapting presentation', () => {
    for (const opening of data.openings) {
      const source = scene.openings.find((item) => item.source_aperture_id === opening.sourceApertureId)
      expect(opening.segment).toEqual(source.segment_gu.map((point) => ({
        x: parseRational(point[0]),
        y: parseRational(point[1]),
      })))
    }
  })

  it('derives room labels and bathroom debug aids solely from forwarded accepted annotations', () => {
    expect(data.rooms.map((room) => room.id)).toEqual(scene.inspection_annotations.rooms.map((room) => room.id))
    for (const room of data.rooms) {
      const source = scene.inspection_annotations.rooms.find((item) => item.id === room.id)
      expect(room.position).toEqual({ x: parseRational(source.label_gu[0]), y: parseRational(source.label_gu[1]) })
      expect(room.classification).toContain('accepted approximate XY')
    }
    expect(data.fixtureDebugAids.map((item) => item.id).sort()).toEqual([
      'bath.shower', 'bath.toilet', 'bath.vanity',
    ])
    for (const fixture of data.fixtureDebugAids) {
      const source = scene.inspection_annotations.objects.find((item) => item.id === fixture.id)
      expect(fixture.rect).toEqual(Object.fromEntries(Object.entries(source.rect_gu).map(([key, value]) => [key, parseRational(value)])))
      expect(fixture.classification).toBe('accepted approximate XY / provisional 3D debug aid')
    }
  })

  it('keeps overlays and debug aids out of authoritative wall and aperture geometry', () => {
    expect(data.walls.map((wall) => wall.outer)).toEqual(scene.wall_extrusions.map((wall) => wall.footprint_gu.outer.map((point) => ({
      x: parseRational(point[0]), y: parseRational(point[1]),
    }))))
    expect(data.openings.map((opening) => opening.segment)).toEqual(scene.openings.map((opening) => opening.segment_gu.map((point) => ({
      x: parseRational(point[0]), y: parseRational(point[1]),
    }))))
  })

  it('keeps wall provenance available for architecture inspection without inventing semantic wall bindings', () => {
    for (const wall of data.walls) {
      const source = scene.wall_extrusions.find((item) => item.id === wall.id)
      expect(wall.inspection.sourcePolygonId).toBe(source.source_polygon_id)
      expect(wall.inspection.sourceContourSegments.length).toBeGreaterThan(0)
      expect(wall.inspection.semanticWallVolumeId).toBeNull()
      expect(wall.inspection.classification).toContain('authoritative accepted XY')
    }
    for (const opening of data.openings) {
      expect(opening.inspection.sourceApertureId).toBe(opening.sourceApertureId)
      expect(opening.inspection.semanticWallVolumeId).toBe(opening.hostWallId)
      expect(opening.inspection.semanticFaceId).toBe(opening.hostFaceId)
    }
  })

  it('treats overlay visibility as presentation-only and leaves adapted XY immutable', () => {
    const before = JSON.stringify({ walls: data.walls.map((wall) => wall.outer), openings: data.openings.map((opening) => opening.segment) })
    const overlayVisibility = { rooms: false, fixtures: false, openings: true, architecture: true }
    expect(overlayVisibility).toEqual({ rooms: false, fixtures: false, openings: true, architecture: true })
    expect(JSON.stringify({ walls: data.walls.map((wall) => wall.outer), openings: data.openings.map((opening) => opening.segment) })).toBe(before)
  })

  it('binds accepted north cutaway and Bedroom C only through their named wall/face selectors', () => {
    expect(data.presentation.cutaway).toMatchObject({
      wallId: 'wall_volume.exterior.bedroom_north',
      faceId: 'wall_face.exterior.bedroom_north.exterior_north',
      lipHeightGu: 72,
      lipStatus: 'provisional',
    })
    expect(data.presentation.bedroom).toMatchObject({
      wallId: 'wall_volume.bedroom.south_desk_facing',
      faceId: 'wall_face.bedroom.south_desk_facing.bedroom_north',
    })
    expect(Object.keys(data.presentation.cutaway).sort()).toEqual([
      'bounds', 'faceId', 'lipHeightGu', 'lipStatus', 'wallId',
    ])
    const cutaway = scene.visibility_treatments.find((item) => item.id === 'visibility.global_cutaway')
    expect(data.presentation.cutaway.lipHeightGu).toBe(cutaway.parameters.inspection_lip_height_gu)
    expect(Object.keys(data.presentation.bedroom).sort()).toEqual([
      'faceBounds', 'faceId', 'faceNormal', 'solidBaseHeightGu', 'upperOpacity', 'wallId',
    ])
  })

  it('offers explicit provisional cutaway candidates through stable accepted semantic selectors only', () => {
    const candidates = Object.fromEntries(data.presentation.cutawayCandidates.map((candidate) => [candidate.id, candidate]))
    expect(candidates.legacy_b.targets.map(({ wallId, faceId }) => [wallId, faceId])).toEqual([
      ['wall_volume.exterior.south_entry', 'wall_face.exterior.south_entry.exterior_south'],
    ])
    expect(candidates.accepted_north.targets.map(({ wallId, faceId }) => [wallId, faceId])).toEqual([
      ['wall_volume.exterior.bedroom_north', 'wall_face.exterior.bedroom_north.exterior_north'],
      ['wall_volume.living.balcony_north', 'wall_face.living.balcony_north.balcony_north'],
    ])
    expect(candidates.accepted_north.targets.map((target) => target.wallId)).not.toContain('wall_volume.bedroom_living.projector_divider')
    expect(candidates.accepted_north.targets.map((target) => target.wallId)).not.toContain('wall_volume.bath.hall_east')
    expect(candidates.none.targets).toEqual([])
    expect(candidates.bedroom_north_west).toMatchObject({
      available: false,
      missingStableSelector: 'No accepted stable semantic wall-volume/face pair identifies the west exterior shell.',
    })
    expect(candidates.accepted_north.targets.map((target) => target.faceId)).not.toContain(data.presentation.bedroom.faceId)
    expect(data.presentation.bedroom).toMatchObject({
      wallId: 'wall_volume.bedroom.south_desk_facing',
      solidBaseHeightGu: 92,
      upperOpacity: 0.34,
    })
  })

  it('keeps cutaway candidates presentation-only without changing scene data or candidate camera', () => {
    const before = JSON.stringify({ fingerprint: scene.fingerprint, walls: scene.wall_extrusions, openings: scene.openings })
    const candidate = perspectiveCandidate(data.bounds, 16 / 9, data.camera)
    const selections = data.presentation.cutawayCandidates.filter((item) => item.available).map((item) => item.id)
    expect(selections).toEqual(['legacy_b', 'accepted_north', 'none'])
    expect(JSON.stringify({ fingerprint: scene.fingerprint, walls: scene.wall_extrusions, openings: scene.openings })).toBe(before)
    expect(perspectiveCandidate(data.bounds, 16 / 9, data.camera)).toEqual(candidate)
  })

  it('has no camera-depth selector or wall-band/family/preflight dependency', () => {
    const source = readFileSync(path.join(toolDirectory, 'adapter.js'), 'utf8')
    const rendererSource = readFileSync(path.join(toolDirectory, 'main.js'), 'utf8')
    expect(source).not.toMatch(/cameraDepth|depthSelector|camera\.position/)
    expect(source).not.toMatch(/nearestWall|nearest-wall|camera.*cutaway/i)
    expect(rendererSource).not.toMatch(/cameraDepth|depthSelector|nearestWall|nearest-wall/i)
    expect(source).not.toMatch(/PhysicalWallBandAuthority|PhysicalFamily(?:Preflight|Authority)/)
  })

  it('uses an inspection artifact generated from the current GeometryScene fingerprint', () => {
    const summary = execFileSync(
      process.platform === 'win32' ? 'python' : 'python3',
      ['scripts/compile_apartment_canvas_geometry_scene.py', '--summary'],
      { cwd: repositoryDirectory, encoding: 'utf8' },
    )
    expect(summary).toContain(`fingerprint=${scene.fingerprint}`)
  })
})
