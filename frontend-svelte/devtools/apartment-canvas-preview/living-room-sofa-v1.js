import * as THREE from 'three'
import { resolveLivingRoomSofaPhysicalWorld } from './physical-world-v1.js'

const physical = resolveLivingRoomSofaPhysicalWorld()

const upholstery = new THREE.MeshStandardMaterial({
  color: 0x5a3b3d,
  roughness: 0.96,
})

function addBox(world, width, length, height, x, y, z, name) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, length, height), upholstery)
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

export function addLivingRoomSofaV1(world) {
  const sofa = physical.sofa
  const f = sofa.plan_bounds_gu
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const structuralHeight = sofa.dimensions_gu.high
  const seatHeight = sofa.seat_height_gu
  const group = new THREE.Group()
  group.name = 'Living Room measured sofa minimal baseline'
  world.add(group)

  // Deliberately minimal: this is only the measured envelope and wall-facing
  // orientation checkpoint, not a fidelity reconstruction.
  addBox(group, f.w - 8, f.h - 12, seatHeight, cx, cy, seatHeight / 2, 'Living Room sofa measured lower body')

  const backBottom = seatHeight - 18
  const backHeight = structuralHeight - backBottom
  addBox(group, 28, f.h - 48, backHeight, f.maxX - 14, cy, backBottom + backHeight / 2, 'Living Room sofa simple continuous structural back')

  const armWidth = 44
  const armHeight = structuralHeight * 0.82
  addBox(group, f.w - 4, armWidth, armHeight, cx, f.y + armWidth / 2, armHeight / 2, 'Living Room sofa north simple arm mass')
  addBox(group, f.w - 4, armWidth, armHeight, cx, f.maxY - armWidth / 2, armHeight / 2, 'Living Room sofa south simple arm mass')
}
