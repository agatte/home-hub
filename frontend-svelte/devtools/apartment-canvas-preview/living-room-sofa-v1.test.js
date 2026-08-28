import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { inchesToGu, physicalWorldV1, resolveBedroomPhysicalWorld, resolveLivingRoomSofaPhysicalWorld } from './physical-world-v1.js'
import { addLivingRoomSofaV1 } from './living-room-sofa-v1.js'

const living = resolveLivingRoomSofaPhysicalWorld()

function renderMinimalSofa() {
  const world = new THREE.Group()
  addLivingRoomSofaV1(world)
  world.updateMatrixWorld(true)
  return world.children.find((child) => child.name === 'Living Room measured sofa minimal baseline')
}

function bounds(item) {
  return new THREE.Box3().setFromObject(item)
}

describe('Living Room measured sofa Physical World v1', () => {
  it('derives the 94 × 42 × 32in envelope and 19.5in seat height from the one apartment calibration', () => {
    const { sofa } = living
    expect(physicalWorldV1.calibrations.apartment_physical_v1.gu_per_in).toBe(3.39)
    expect(sofa.physical_dimensions_in).toEqual({ long: 94, deep: 42, high: 32, seat_high: 19.5 })
    expect(sofa.dimensions_gu.long).toBeCloseTo(inchesToGu(94), 10)
    expect(sofa.dimensions_gu.deep).toBeCloseTo(inchesToGu(42), 10)
    expect(sofa.dimensions_gu.high).toBeCloseTo(inchesToGu(32), 10)
    expect(sofa.seat_height_gu).toBeCloseTo(inchesToGu(19.5), 10)
    expect(sofa.calibration_ref).toBe('apartment_physical_v1')
  })

  it('anchors the rear structural edge flush to the finished room-side wall plane', () => {
    const { sofa, architecture } = living
    expect(architecture.finishedBackWall.room_side_plane_x_gu).toBe(981.29)
    expect(sofa.rear_edge_x_gu).toBe(architecture.finishedBackWall.room_side_plane_x_gu)
    expect(sofa.plan_bounds_gu.maxX).toBeCloseTo(architecture.finishedBackWall.room_side_plane_x_gu, 10)
    expect(sofa.orientation).toEqual({ long_axis: '+y', depth_axis: '-x', rear_face: '+x' })
  })

  it('does not move Bedroom authority or mutate the accepted GeometryScene fingerprint', () => {
    const bedroom = resolveBedroomPhysicalWorld()
    expect(bedroom.objects.bed.plan_bounds_gu).toMatchObject({ x: 13.83, y: 70, w: inchesToGu(84), h: inchesToGu(64.1) })
    const root = path.dirname(fileURLToPath(import.meta.url))
    const scene = JSON.parse(readFileSync(path.join(root, '../apartment-whitebox/generated/geometry-scene.json'), 'utf8'))
    expect(scene.fingerprint).toBe('ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43')
  })

  it('renders only the measured baseline volumes inside the sofa envelope', () => {
    const sofa = renderMinimalSofa()
    const f = living.sofa.plan_bounds_gu
    const parts = sofa.children
    const back = parts.find((part) => part.name.includes('continuous structural back'))

    expect(parts.map((part) => part.name)).toEqual([
      'Living Room sofa measured lower body',
      'Living Room sofa simple continuous structural back',
      'Living Room sofa north simple arm mass',
      'Living Room sofa south simple arm mass',
    ])
    expect(bounds(back).max.x).toBeCloseTo(f.maxX, 5)
    expect(parts.every((part) => {
      const box = bounds(part)
      return box.min.x >= f.x && box.max.x <= f.maxX && box.min.y >= f.y && box.max.y <= f.maxY
    })).toBe(true)
  })
})
