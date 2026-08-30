import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addLivingRoomFurnitureV1, RUG_RENDER_FOOTPRINT } from './living-room-furniture-v1.js'
import { resolveLivingRoomSofaPhysicalWorld } from './physical-world-v1.js'

function bounds(item) {
  return new THREE.Box3().setFromObject(item)
}

function renderFurniture() {
  const world = new THREE.Group()
  addLivingRoomFurnitureV1(world, adaptGeometryScene(geometryScene))
  world.updateMatrixWorld(true)
  return world.children.find((child) => child.name === 'Living Room visual furniture identity v1')
}

describe('Living Room visual furniture identity v1', () => {
  it('keeps the existing presentation rug footprint short of the measured sofa', () => {
    const sofa = resolveLivingRoomSofaPhysicalWorld().sofa.plan_bounds_gu
    expect(RUG_RENDER_FOOTPRINT.x + RUG_RENDER_FOOTPRINT.w).toBeLessThan(sofa.x)
  })

  it('renders a restrained rug, warm wood / black-metal coffee table, and rounded swivel chair', () => {
    const group = renderFurniture()
    const names = []
    group.traverse((item) => names.push(item.name))

    expect(names).toContain('Living Room neutral patterned rug base')
    expect(names).toContain('Living Room coffee table warm wood top')
    expect(names).toContain('Living Room coffee table black metal front lower rail')
    expect(names).toContain('Living Room white swivel chair rounded bouclé shell')
    expect(names).toContain('Living Room white swivel chair black round base')

    const table = group.children.find((item) => item.name === 'Living Room coffee table warm wood top')
    const shell = group.children.find((item) => item.name === 'Living Room white swivel chair rounded bouclé shell')
    expect(bounds(table).max.z).toBeGreaterThan(60)
    expect(bounds(shell).max.z).toBeGreaterThan(50)
  })
})
