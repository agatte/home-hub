import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'

// These are deliberately renderer-only identity treatments. The object
// anchors remain the existing GeometryScene compatibility footprints; no
// physical-world dimensions, coordinates, or calibration are asserted here.
const materials = Object.freeze({
  rugBase: new THREE.MeshStandardMaterial({ color: 0xb8afa3, roughness: 1 }),
  rugPattern: new THREE.MeshStandardMaterial({ color: 0x958b80, roughness: 1, transparent: true, opacity: 0.22 }),
  coffeeTop: new THREE.MeshStandardMaterial({ color: 0x6f5337, roughness: 0.9 }),
  coffeeTopEdge: new THREE.MeshStandardMaterial({ color: 0x4b3424, roughness: 0.84 }),
  coffeeMetal: new THREE.MeshStandardMaterial({ color: 0x232625, roughness: 0.6, metalness: 0.16 }),
  chairBoucle: new THREE.MeshStandardMaterial({ color: 0xe2ddd2, roughness: 1 }),
  chairSeat: new THREE.MeshStandardMaterial({ color: 0xd0c9bd, roughness: 1 }),
  chairBase: new THREE.MeshStandardMaterial({ color: 0x2d302f, roughness: 0.62, metalness: 0.16 }),
})

// Kept equal to the prior presentation-only rug treatment. It intentionally
// stops before the measured sofa's room-facing edge; it is not a measurement.
export const RUG_RENDER_FOOTPRINT = Object.freeze({ x: 580, y: 234.34, w: 244.08, h: 366.12 })

function footprint(data, id) {
  const blocker = data.blockers.find((item) => item.id === id)
  return blocker ? blocker.renderFootprint ?? blocker.sourceFootprint : null
}

function addBox(world, width, length, height, x, y, z, material, name, radius = 0) {
  const geometry = radius > 0
    ? new RoundedBoxGeometry(width, length, height, 5, radius)
    : new THREE.BoxGeometry(width, length, height)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addEllipsoid(world, x, y, w, h, zMin, zMax, material, name) {
  const geometry = new THREE.SphereGeometry(1, 28, 18)
  geometry.scale(w / 2, h / 2, (zMax - zMin) / 2)
  geometry.translate(x + w / 2, y + h / 2, (zMin + zMax) / 2)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.name = name
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addRug(world) {
  const f = RUG_RENDER_FOOTPRINT
  addBox(world, f.w, f.h, 0.62, f.x + f.w / 2, f.y + f.h / 2, 1.02, materials.rugBase, 'Living Room neutral patterned rug base')

  // Broad, quiet bands retain the reference rug's worn low-contrast read
  // without attempting its micro-texture.
  for (const ratio of [0.23, 0.51, 0.78]) {
    addBox(world, f.w * 0.88, 4.2, 0.06, f.x + f.w / 2, f.y + f.h * ratio, 1.37, materials.rugPattern, 'Living Room rug restrained pattern band')
  }
}

function addCoffeeTable(world, data) {
  const f = footprint(data, 'living.coffee_table')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2

  addBox(world, f.w * 0.94, f.h * 0.96, 5.6, cx, cy, 59.4, materials.coffeeTop, 'Living Room coffee table warm wood top', 1.2)
  addBox(world, f.w * 0.955, f.h * 0.975, 1.2, cx, cy, 55.9, materials.coffeeTopEdge, 'Living Room coffee table dark wood top edge', 0.8)

  const legW = Math.max(4.6, f.w * 0.058)
  const legL = Math.max(5.2, f.h * 0.036)
  for (const x of [f.x + legW, f.x + f.w - legW]) {
    for (const y of [f.y + legL, f.y + f.h - legL]) {
      addBox(world, legW, legL, 54, x, y, 27, materials.coffeeMetal, 'Living Room coffee table black metal corner leg', 0.6)
    }
  }
  addBox(world, f.w * 0.91, 3.8, 3.8, cx, f.y + 3.2, 4.1, materials.coffeeMetal, 'Living Room coffee table black metal front lower rail', 0.5)
  addBox(world, f.w * 0.91, 3.8, 3.8, cx, f.y + f.h - 3.2, 4.1, materials.coffeeMetal, 'Living Room coffee table black metal rear lower rail', 0.5)
}

function addWhiteSwivelChair(world, data) {
  const f = footprint(data, 'living.white_chair')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const baseRadius = Math.min(f.w, f.h) * 0.16
  const base = new THREE.Mesh(new THREE.CylinderGeometry(baseRadius * 1.12, baseRadius, 9, 28), materials.chairBase)
  base.name = 'Living Room white swivel chair black round base'
  base.rotation.x = Math.PI / 2
  base.position.set(cx, cy, 4.5)
  base.castShadow = true
  base.receiveShadow = true
  world.add(base)

  addEllipsoid(world, f.x + f.w * 0.055, f.y + f.h * 0.06, f.w * 0.89, f.h * 0.88, 8, 59, materials.chairBoucle, 'Living Room white swivel chair rounded bouclé shell')
  addEllipsoid(world, f.x + f.w * 0.1, f.y + f.h * 0.015, f.w * 0.8, f.h * 0.61, 47, 91, materials.chairBoucle, 'Living Room white swivel chair rounded back shell')
  addBox(world, f.w * 0.61, f.h * 0.46, 10, cx, f.y + f.h * 0.57, 59, materials.chairSeat, 'Living Room white swivel chair inset seat cushion', 10)
}

export function addLivingRoomFurnitureV1(world, data) {
  const group = new THREE.Group()
  group.name = 'Living Room visual furniture identity v1'
  world.add(group)
  addRug(group)
  addCoffeeTable(group, data)
  addWhiteSwivelChair(group, data)
}
