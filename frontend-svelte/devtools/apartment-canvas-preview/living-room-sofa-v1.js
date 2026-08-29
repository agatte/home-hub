import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { resolveLivingRoomSofaPhysicalWorld } from './physical-world-v1.js'

const physical = resolveLivingRoomSofaPhysicalWorld()

const upholstery = new THREE.MeshStandardMaterial({
  color: 0x5a3b3d,
  roughness: 0.96,
})

const backPillowUpholstery = new THREE.MeshStandardMaterial({
  color: 0x59614a,
  roughness: 0.98,
})

const carvedWood = new THREE.MeshStandardMaterial({
  // The reference reads as dark walnut, but it remains visibly warmer and
  // lighter than the deepest upholstery and cast shadows.
  color: 0x34211b,
  roughness: 0.66,
  metalness: 0,
})

function addBox(world, width, length, height, x, y, z, name, material = upholstery) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, length, height), material)
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function roundedRectGeometry(width, length, height, radius = 4) {
  const r = Math.min(radius, width / 2 - 0.1, length / 2 - 0.1)
  const shape = new THREE.Shape()
  shape.moveTo(-width / 2 + r, -length / 2)
  shape.lineTo(width / 2 - r, -length / 2)
  shape.quadraticCurveTo(width / 2, -length / 2, width / 2, -length / 2 + r)
  shape.lineTo(width / 2, length / 2 - r)
  shape.quadraticCurveTo(width / 2, length / 2, width / 2 - r, length / 2)
  shape.lineTo(-width / 2 + r, length / 2)
  shape.quadraticCurveTo(-width / 2, length / 2, -width / 2, length / 2 - r)
  shape.lineTo(-width / 2, -length / 2 + r)
  shape.quadraticCurveTo(-width / 2, -length / 2, -width / 2 + r, -length / 2)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: height,
    bevelEnabled: true,
    bevelSegments: 3,
    bevelSize: Math.min(2.2, height * 0.22),
    bevelThickness: Math.min(1.2, height * 0.15),
  })
  geometry.translate(0, 0, -height / 2)
  return geometry
}

function addRoundedBox(world, width, length, height, x, y, z, name, radius = 4, material = upholstery) {
  const mesh = new THREE.Mesh(roundedRectGeometry(width, length, height, radius), material)
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addSoftRoundedBox(world, width, length, height, x, y, z, name, radius, material = upholstery) {
  const mesh = new THREE.Mesh(
    new RoundedBoxGeometry(width, length, height, 5, radius),
    material,
  )
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addFrontFoot(world, x, y, name) {
  // Bounded, flared support: the foot reads as a carved termination instead
  // of a tall arm-front column.
  const plinth = addRoundedBox(world, 24, 22, 6, x, y, 4, `${name} stepped plinth`, 3, carvedWood)
  const foot = addRoundedBox(world, 17, 17, 21, x, y, 14.5, name, 4, carvedWood)
  return { plinth, foot }
}

function addRolledArm(world, side, f, armWidth, armY, structuralHeight) {
  const arm = new THREE.Group()
  arm.name = `Living Room sofa ${side} rolled arm assembly`
  world.add(arm)

  const armBodyHeight = 73
  addRoundedBox(
    arm,
    f.w - 8,
    armWidth,
    armBodyHeight,
    f.x + f.w / 2,
    armY,
    armBodyHeight / 2,
    `Living Room sofa ${side} lower upholstered arm body`,
    8,
  )

  // This short, broad rounded volume overlaps the body. It gives the arm its
  // traditional padded roll rather than reading as a pipe set on a wall.
  const rollWidth = f.w - 40
  addSoftRoundedBox(
    arm,
    rollWidth,
    armWidth - 4,
    34,
    f.x + 20 + rollWidth / 2,
    armY,
    structuralHeight - 22,
    `Living Room sofa ${side} thick upholstered rolled top`,
    12,
  )

  // The wood is a restrained room-facing appliqué, not an arm-face shell:
  // a small scroll accent joins a narrow descending strip and bounded foot.
  addRoundedBox(
    arm,
    8,
    22,
    15,
    f.x + 6,
    armY,
    72,
    `Living Room sofa ${side} room-facing carved wood upper scroll accent`,
    6,
    carvedWood,
  )
  addRoundedBox(
    arm,
    7,
    16,
    43,
    f.x + 5.5,
    armY,
    43.5,
    `Living Room sofa ${side} room-facing carved wood descending strip`,
    5,
    carvedWood,
  )
  addFrontFoot(
    arm,
    f.x + 15,
    armY,
    `Living Room sofa ${side} dark carved front foot`,
  )

  return arm
}

function addRoundedPillowBody(world, depth, width, height, x, y, z, name, radius = 6) {
  // RoundedBoxGeometry receives dimensions on its local X, Y, Z axes. Keeping
  // the pillow's depth on X preserves its established room-facing -X face.
  const mesh = new THREE.Mesh(
    new RoundedBoxGeometry(depth, width, height, 4, radius),
    backPillowUpholstery,
  )
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addOliveBolster(world, x, y, z, name) {
  // Capsule geometry preserves a soft cylindrical pillow silhouette without
  // introducing separate structural-looking end pieces.
  const mesh = new THREE.Mesh(
    new THREE.CapsuleGeometry(10, 38, 6, 12),
    backPillowUpholstery,
  )
  mesh.name = name
  mesh.position.set(x, y, z)
  mesh.rotation.z = Math.PI / 2
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
  const armEdgeInset = 2.5
  addRolledArm(group, 'north', f, armWidth, f.y + armWidth / 2 + armEdgeInset, structuralHeight)
  addRolledArm(group, 'south', f, armWidth, f.maxY - armWidth / 2 - armEdgeInset, structuralHeight)

  // Visible just below the upholstery on the coffee-table/room-facing (-X)
  // side; the rail stays visually secondary to the two carved arm fronts.
  addRoundedBox(
    group,
    10,
    f.h - 50,
    11,
    f.x + 7.2,
    cy,
    12,
    'Living Room sofa room-facing dark lower front wood rail',
    3,
    carvedWood,
  )

  // The photos establish two large, separately readable brown/mauve cushions.
  // They are deliberately limited to one soft-edged primitive each: no seams,
  // wrinkles, back pillows, or other fidelity layers belong in this pass.
  const cushionWidth = 108
  const cushionDepth = 89.4
  const cushionHeight = 20
  const centerGap = 8
  const cushionX = f.x + 13 + cushionDepth / 2
  const cushionY = f.y + armWidth + 3.33 + cushionWidth / 2
  const cushionZ = seatHeight - 2 + cushionHeight / 2
  addRoundedBox(group, cushionDepth, cushionWidth, cushionHeight, cushionX, cushionY, cushionZ, 'Living Room sofa north brown seat cushion', 6)
  addRoundedBox(group, cushionDepth, cushionWidth, cushionHeight, cushionX, cushionY + cushionWidth + centerGap, cushionZ, 'Living Room sofa south brown seat cushion', 6)

  // Four large, plain loose back pillows supply the photo-established backrest
  // composition. `addRoundedBox(depth, width, height)` maps to local X, Y, Z:
  // -X is the room-facing broad face; +X is the structural-back-facing broad
  // face. The sofa itself has no world rotation, so this keeps every front
  // face directed toward world -X (the coffee-table side).
  const neutralBackPillowOrientation = Object.freeze({
    lean: 0.14, // rotate around the sofa-long local Y axis: top leans toward +X/the wall
    yaw: 0, // rotate around local Z; keep the broad face front-on at neutral
  })
  const backPillows = [
    { depth: 34, width: 72, height: 64, x: 925.5, y: 395, z: 98, leanOffset: 0, yawOffset: -0.018, name: 'Living Room sofa north olive loose back pillow' },
    { depth: 30, width: 66, height: 68, x: 929, y: 451, z: 104, leanOffset: -0.01, yawOffset: -0.006, name: 'Living Room sofa inner-north olive loose back pillow' },
    { depth: 32, width: 70, height: 63, x: 926, y: 505, z: 99, leanOffset: 0.005, yawOffset: 0.008, name: 'Living Room sofa inner-south olive loose back pillow' },
    { depth: 31, width: 72, height: 66, x: 928, y: 557, z: 103, leanOffset: -0.005, yawOffset: 0.018, name: 'Living Room sofa south olive loose back pillow' },
  ]
  for (const pillow of backPillows) {
    const item = addRoundedPillowBody(group, pillow.depth, pillow.width, pillow.height, pillow.x, pillow.y, pillow.z, pillow.name)
    item.rotation.set(
      0,
      neutralBackPillowOrientation.lean + pillow.leanOffset,
      neutralBackPillowOrientation.yaw + pillow.yawOffset,
      'XYZ',
    )
  }

  // The two loose bolsters are secondary cushions along the arms' inside
  // edges; they sit on the seat rather than changing either arm assembly.
  addOliveBolster(group, f.x + 50, f.y + 55, 86, 'Living Room sofa north olive bolster pillow')
  addOliveBolster(group, f.x + 50, f.maxY - 55, 86, 'Living Room sofa south olive bolster pillow')
}
