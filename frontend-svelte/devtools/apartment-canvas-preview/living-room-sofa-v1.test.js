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

function planOverlapArea(first, second) {
  const a = bounds(first)
  const b = bounds(second)
  return Math.max(0, Math.min(a.max.x, b.max.x) - Math.max(a.min.x, b.min.x))
    * Math.max(0, Math.min(a.max.y, b.max.y) - Math.max(a.min.y, b.min.y))
}

function center(item) {
  return item.position
}

function worldDirection(item, localDirection) {
  item.updateWorldMatrix(true, false)
  return localDirection.clone().transformDirection(item.matrixWorld)
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

  it('renders the accepted shell, rolled arms, and two accepted brown seat cushions inside the sofa footprint', () => {
    const sofa = renderMinimalSofa()
    const f = living.sofa.plan_bounds_gu
    const parts = sofa.children
    const back = parts.find((part) => part.name.includes('continuous structural back'))
    const cushions = parts.filter((part) => part.name.includes('brown seat cushion'))
    const armAssemblies = parts.filter((part) => part.name.includes('rolled arm assembly'))

    expect(armAssemblies.map((part) => part.name)).toEqual([
      'Living Room sofa north rolled arm assembly',
      'Living Room sofa south rolled arm assembly',
    ])
    expect(bounds(back).max.x).toBeCloseTo(f.maxX, 5)
    expect(armAssemblies.every((arm) => {
      const box = bounds(arm)
      return box.min.x >= f.x - 0.3 && box.max.x <= f.maxX + 0.3
        && box.min.y >= f.y - 0.3 && box.max.y <= f.maxY + 0.3
    })).toBe(true)
    expect(cushions.map((part) => part.name)).toEqual([
      'Living Room sofa north brown seat cushion',
      'Living Room sofa south brown seat cushion',
    ])
    expect(cushions).toHaveLength(2)
    expect(planOverlapArea(cushions[0], cushions[1])).toBe(0)
    expect(cushions.every((part) => {
      const box = bounds(part)
      return box.min.x >= f.x && box.max.x <= f.maxX && box.min.y >= f.y && box.max.y <= f.maxY
    })).toBe(true)
  })

  it('keeps the two accepted brown seat cushions unchanged', () => {
    const sofa = renderMinimalSofa()
    const cushions = sofa.children.filter((part) => part.name.includes('brown seat cushion'))

    const expected = [
      { name: 'Living Room sofa north brown seat cushion', x: 896.61, y: 417.03, z: 74.105 },
      { name: 'Living Room sofa south brown seat cushion', x: 896.61, y: 533.03, z: 74.105 },
    ]
    cushions.forEach((cushion, index) => {
      const expectedCushion = expected[index]
      const box = bounds(cushion)
      expect(cushion.name).toBe(expectedCushion.name)
      expect(center(cushion).x).toBeCloseTo(expectedCushion.x, 10)
      expect(center(cushion).y).toBeCloseTo(expectedCushion.y, 10)
      expect(center(cushion).z).toBeCloseTo(expectedCushion.z, 10)
      expect(box.max.x - box.min.x).toBeCloseTo(93.8, 4)
      expect(box.max.y - box.min.y).toBeCloseTo(112.4, 4)
      expect(box.max.z - box.min.z).toBeCloseTo(22.4, 4)
    })
  })

  it('keeps the accepted upholstered arm bodies and rolled tops unchanged', () => {
    const sofa = renderMinimalSofa()
    const f = living.sofa.plan_bounds_gu
    const armAssemblies = sofa.children.filter((part) => part.name.includes('rolled arm assembly'))

    armAssemblies.forEach((arm, index) => {
      const body = arm.children.find((part) => part.name.includes('lower upholstered arm body'))
      const roll = arm.children.find((part) => part.name.includes('thick upholstered rolled top'))
      expect(body).toBeDefined()
      expect(roll).toBeDefined()
      expect(center(body).x).toBeCloseTo(910.1, 10)
      expect(center(body).y).toBeCloseTo(index === 0 ? 340.2 : 609.86, 10)
      expect(center(body).z).toBeCloseTo(36.5, 10)
      expect(center(roll).x).toBeCloseTo(910.1, 10)
      expect(center(roll).y).toBeCloseTo(index === 0 ? 340.2 : 609.86, 10)
      expect(center(roll).z).toBeCloseTo(86.48, 10)
      expect(bounds(body).max.x).toBeLessThanOrEqual(f.maxX)
      expect(bounds(roll).min.x).toBeGreaterThanOrEqual(f.x)
    })
  })

  it('keeps dark-walnut carved wood bounded to the room-facing arm-front contour', () => {
    const sofa = renderMinimalSofa()
    const f = living.sofa.plan_bounds_gu
    const armWidth = 44
    const armAssemblies = sofa.children.filter((part) => part.name.includes('rolled arm assembly'))
    const rail = sofa.children.find((part) => part.name.includes('dark lower front wood rail'))

    expect(rail).toBeDefined()
    expect(bounds(rail).min.x).toBeCloseTo(f.x, 5)
    expect(bounds(rail).max.x).toBeLessThan(f.x + 15)
    armAssemblies.forEach((arm) => {
      const upperAccent = arm.children.find((part) => part.name.includes('room-facing carved wood upper scroll accent'))
      const descendingStrip = arm.children.find((part) => part.name.includes('room-facing carved wood descending strip'))
      const foot = arm.children.find((part) => part.name.endsWith('dark carved front foot'))
      const plinth = arm.children.find((part) => part.name.endsWith('dark carved front foot stepped plinth'))
      expect(upperAccent).toBeDefined()
      expect(descendingStrip).toBeDefined()
      expect(foot).toBeDefined()
      expect(plinth).toBeDefined()
      ;[upperAccent, descendingStrip, foot, plinth].forEach((part) => {
        const box = bounds(part)
        expect(box.min.x).toBeGreaterThanOrEqual(f.x - 0.3)
        expect(box.max.x).toBeLessThan(f.x + 30)
      })
      expect(bounds(upperAccent).max.y - bounds(upperAccent).min.y).toBeLessThan(armWidth * 0.6)
      expect(bounds(descendingStrip).max.y - bounds(descendingStrip).min.y).toBeLessThan(armWidth * 0.5)
      expect(bounds(descendingStrip).min.z).toBeLessThan(bounds(upperAccent).min.z)
      expect(bounds(foot).max.z - bounds(foot).min.z).toBeGreaterThan(18)
      expect(bounds(foot).min.x).toBeGreaterThanOrEqual(f.x)
      expect(bounds(foot).max.x).toBeLessThanOrEqual(f.maxX)
      expect(foot.material.color.getHex()).toBe(0x34211b)
      expect(foot.material.roughness).toBe(0.66)
    })
  })

  it('keeps all four olive pillow broad faces room-side, in front of the structural back, and above/behind the seat cushions', () => {
    const sofa = renderMinimalSofa()
    const f = living.sofa.plan_bounds_gu
    const back = sofa.children.find((part) => part.name.includes('continuous structural back'))
    const cushions = sofa.children.filter((part) => part.name.includes('brown seat cushion'))
    const pillows = sofa.children.filter((part) => part.name.includes('olive loose back pillow'))
    const backBounds = bounds(back)

    expect(pillows.map((pillow) => pillow.name)).toEqual([
      'Living Room sofa north olive loose back pillow',
      'Living Room sofa inner-north olive loose back pillow',
      'Living Room sofa inner-south olive loose back pillow',
      'Living Room sofa south olive loose back pillow',
    ])
    expect(pillows).toHaveLength(4)
    expect(pillows.map((pillow) => center(pillow).toArray())).toEqual([
      [925.5, 395, 98],
      [929, 451, 104],
      [926, 505, 99],
      [928, 557, 103],
    ])
    expect(pillows.every((pillow) => {
      const box = bounds(pillow)
      return box.max.x <= backBounds.min.x
        && box.min.y >= f.y && box.max.y <= f.maxY
        && center(pillow).x > cushions[0].position.x
        && center(pillow).z > cushions[0].position.z
    })).toBe(true)
    expect(pillows.slice(0, -1).every((pillow, index) => planOverlapArea(pillow, pillows[index + 1]) > 0)).toBe(true)
    ;[0.14, 0.13, 0.145, 0.135].forEach((lean, index) => {
      expect(pillows[index].rotation.y).toBeCloseTo(lean, 10)
    })
    ;[-0.018, -0.006, 0.008, 0.018].forEach((yaw, index) => {
      expect(pillows[index].rotation.z).toBeCloseTo(yaw, 10)
    })
    expect(pillows.every((pillow) => {
      const roomFacingBroadFace = worldDirection(pillow, new THREE.Vector3(-1, 0, 0))
      return roomFacingBroadFace.dot(new THREE.Vector3(-1, 0, 0)) > 0.98
        && Math.abs(roomFacingBroadFace.y) < 0.02
        && roomFacingBroadFace.z > 0
    })).toBe(true)
  })
})
