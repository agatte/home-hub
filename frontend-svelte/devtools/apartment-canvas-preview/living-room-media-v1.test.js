import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addLivingRoomMediaV1 } from './living-room-media-v1.js'
import { resolveLivingRoomSofaPhysicalWorld } from './physical-world-v1.js'

function renderMedia() {
  const world = new THREE.Group()
  addLivingRoomMediaV1(world, adaptGeometryScene(geometryScene))
  world.updateMatrixWorld(true)
  return world.children.find((child) => child.name === 'Living Room media cluster visual identity v1')
}

function named(group, name) {
  const matches = []
  group.traverse((item) => { if (item.name === name) matches.push(item) })
  return matches
}

describe('Living Room media visual identity v1', () => {
  it('renders exactly one intended TV, media console, and subwoofer representation', () => {
    const group = renderMedia()
    expect(named(group, 'Living Room TV representation')).toHaveLength(1)
    expect(named(group, 'Living Room media console representation')).toHaveLength(1)
    expect(named(group, 'Living Room subwoofer representation')).toHaveLength(1)
    expect(named(group, 'Living Room TV dark off screen')).toHaveLength(1)
    expect(named(group, 'Living Room subwoofer dark speaker cabinet')).toHaveLength(1)
  })

  it('keeps the subwoofer at the console balcony-end compatibility anchor and leaves no legacy generic media mesh', () => {
    const group = renderMedia()
    const subwoofer = named(group, 'Living Room subwoofer representation')[0]
    const console = named(group, 'Living Room media console representation')[0]
    const subBounds = new THREE.Box3().setFromObject(subwoofer)
    const consoleBounds = new THREE.Box3().setFromObject(console)
    expect(subBounds.max.y).toBeLessThanOrEqual(consoleBounds.min.y + 2)
    expect(named(group, 'Living Room TV stand')).toHaveLength(0)
    expect(named(group, 'Living Room TV')).toHaveLength(0)
    expect(named(group, 'Living Room Sub')).toHaveLength(0)
  })

  it('preserves accepted seating and Physical World / GeometryScene authority', () => {
    const sofa = resolveLivingRoomSofaPhysicalWorld().sofa.plan_bounds_gu
    expect(sofa).toMatchObject({ x: 838.91, y: 315.7, w: 142.38, h: 318.66 })
    const root = path.dirname(fileURLToPath(import.meta.url))
    const scene = JSON.parse(readFileSync(path.join(root, '../apartment-whitebox/generated/geometry-scene.json'), 'utf8'))
    expect(scene.fingerprint).toBe('ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43')
  })
})
