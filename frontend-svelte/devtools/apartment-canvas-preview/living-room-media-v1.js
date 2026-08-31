import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'

// Renderer-only identity treatment. Every plan anchor below comes from the
// existing GeometryScene compatibility footprint; it is deliberately not a
// claim about the physical dimensions, elevation, or product identity.
const materials = Object.freeze({
  consoleWood: new THREE.MeshStandardMaterial({ color: 0x242624, roughness: 0.8 }),
  consoleEdge: new THREE.MeshStandardMaterial({ color: 0x151716, roughness: 0.68 }),
  screen: new THREE.MeshStandardMaterial({ color: 0x0b0e0f, roughness: 0.52, metalness: 0.04 }),
  bezel: new THREE.MeshStandardMaterial({ color: 0x191b1b, roughness: 0.62, metalness: 0.08 }),
  subwoofer: new THREE.MeshStandardMaterial({ color: 0x202221, roughness: 0.93 }),
  grille: new THREE.MeshStandardMaterial({ color: 0x111313, roughness: 1 }),
})

function footprint(data, id) {
  const blocker = data.blockers.find((item) => item.id === id)
  return blocker ? blocker.renderFootprint ?? blocker.sourceFootprint : null
}

function addBox(world, width, length, height, x, y, z, material, name, radius = 0) {
  const geometry = radius > 0
    ? new RoundedBoxGeometry(width, length, height, 4, radius)
    : new THREE.BoxGeometry(width, length, height)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addConsole(world, f) {
  const group = new THREE.Group()
  group.name = 'Living Room media console representation'
  world.add(group)

  const bodyX = f.x + f.w * 0.51
  const bodyY = f.y + f.h / 2
  const bodyW = f.w * 0.86
  const bodyL = f.h * 0.92
  const topZ = 78
  const legH = 9
  const railH = 9

  // A dark, low cabinet with open center shelving is the reference-visible
  // read. The simple carcass deliberately avoids unobservable fittings.
  addBox(group, bodyW, bodyL, railH, bodyX, bodyY, legH + railH / 2, materials.consoleEdge, 'Living Room media console lower rail', 1.2)
  addBox(group, bodyW, bodyL, 5, bodyX, bodyY, topZ - 2.5, materials.consoleEdge, 'Living Room media console broad top', 1)

  const sideW = Math.max(4, bodyW * 0.13)
  for (const y of [bodyY - bodyL / 2 + sideW / 2, bodyY + bodyL / 2 - sideW / 2]) {
    addBox(group, bodyW, sideW, topZ - legH - railH, bodyX, y, legH + railH + (topZ - legH - railH) / 2, materials.consoleWood, 'Living Room media console side cabinet', 1)
  }

  // The rear panel and a single shelf retain a visible open bay without
  // turning the whole unit into an arbitrary cabinet-grid approximation.
  addBox(group, 4, bodyL - sideW * 2, topZ - legH - railH, f.x + f.w * 0.83, bodyY, legH + railH + (topZ - legH - railH) / 2, materials.consoleWood, 'Living Room media console rear panel')
  addBox(group, bodyW * 0.78, bodyL - sideW * 2, 3.8, bodyX - bodyW * 0.04, bodyY, 42, materials.consoleEdge, 'Living Room media console open shelf')

  const legW = Math.max(4, bodyW * 0.12)
  const legL = Math.max(6, bodyL * 0.055)
  for (const x of [bodyX - bodyW / 2 + legW / 2, bodyX + bodyW / 2 - legW / 2]) {
    for (const y of [bodyY - bodyL / 2 + legL / 2, bodyY + bodyL / 2 - legL / 2]) {
      addBox(group, legW, legL, legH, x, y, legH / 2, materials.consoleEdge, 'Living Room media console short leg', 0.8)
    }
  }
}

function addTv(world, f, consoleTopZ) {
  const group = new THREE.Group()
  group.name = 'Living Room TV representation'
  world.add(group)

  const panelW = Math.max(4.4, f.w * 0.34)
  const panelL = f.h * 0.93
  const panelH = 106
  const centerX = f.x + f.w * 0.48
  const centerY = f.y + f.h / 2
  const centerZ = consoleTopZ + panelH / 2 - 2

  addBox(group, panelW, panelL, panelH, centerX, centerY, centerZ, materials.bezel, 'Living Room TV thin dark bezel', 1.1)
  // The seating-facing side is -X. Keep the display dark/off: no live state
  // or content is implied by this static Physical World presentation.
  addBox(group, 0.9, panelL * 0.95, panelH * 0.94, centerX - panelW / 2 - 0.36, centerY, centerZ, materials.screen, 'Living Room TV dark off screen', 0.45)
  addBox(group, 6, 28, 4, centerX + panelW * 0.12, centerY, consoleTopZ + 2, materials.bezel, 'Living Room TV restrained pedestal foot', 0.8)
}

function addSubwoofer(world, f) {
  const group = new THREE.Group()
  group.name = 'Living Room subwoofer representation'
  world.add(group)

  const bodyW = f.w * 0.82
  const bodyL = f.h * 0.84
  const bodyH = 52
  const centerX = f.x + f.w / 2
  const centerY = f.y + f.h / 2
  addBox(group, bodyW, bodyL, bodyH, centerX, centerY, bodyH / 2, materials.subwoofer, 'Living Room subwoofer dark speaker cabinet', 1.8)
  addBox(group, 0.8, bodyL * 0.64, bodyH * 0.62, centerX - bodyW / 2 - 0.32, centerY, bodyH / 2, materials.grille, 'Living Room subwoofer restrained front grille', 0.4)
}

export function addLivingRoomMediaV1(world, data) {
  const tv = footprint(data, 'living.tv')
  const console = footprint(data, 'living.tv_stand')
  const subwoofer = footprint(data, 'living.subwoofer')
  if (!tv || !console || !subwoofer) return

  const group = new THREE.Group()
  group.name = 'Living Room media cluster visual identity v1'
  world.add(group)
  addConsole(group, console)
  addTv(group, tv, 78)
  addSubwoofer(group, subwoofer)
}
