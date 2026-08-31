import * as THREE from 'three'
import { addApartmentDetailsV1 } from './details-v1.js'

const materials = Object.freeze({
  bedRunner: new THREE.MeshStandardMaterial({ color: 0xa79a8c, roughness: 0.99 }),
  headboardFace: new THREE.MeshStandardMaterial({ color: 0x66594f, roughness: 0.96 }),
  chairInset: new THREE.MeshStandardMaterial({ color: 0xbeb5a8, roughness: 0.99 }),
  chairEdge: new THREE.MeshStandardMaterial({ color: 0xd8d1c6, roughness: 0.99 }),
  cabinetKick: new THREE.MeshStandardMaterial({ color: 0xb9b5ad, roughness: 0.94 }),
  cabinetSeam: new THREE.MeshStandardMaterial({ color: 0xc8c4bc, roughness: 0.92 }),
  serviceFace: new THREE.MeshStandardMaterial({ color: 0xc5c8c5, roughness: 0.9 }),
})

function ring(x, y, w, h) {
  return [
    { x, y },
    { x: x + w, y },
    { x: x + w, y: y + h },
    { x, y: y + h },
  ]
}

function shapeFromRing(points) {
  const shape = new THREE.Shape()
  shape.moveTo(points[0].x, points[0].y)
  points.slice(1).forEach((point) => shape.lineTo(point.x, point.y))
  shape.closePath()
  return shape
}

function boxGeometry(x, y, w, h, zMin, zMax) {
  const geometry = new THREE.ExtrudeGeometry(shapeFromRing(ring(x, y, w, h)), {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 1,
  })
  geometry.translate(0, 0, zMin)
  return geometry
}

function ellipsoidGeometry(x, y, w, h, zMin, zMax, segments = 20) {
  const radiusZ = (zMax - zMin) / 2
  const geometry = new THREE.SphereGeometry(1, segments, Math.max(12, Math.round(segments * 0.7)))
  geometry.scale(w / 2, h / 2, radiusZ)
  geometry.translate(x + w / 2, y + h / 2, zMin + radiusZ)
  return geometry
}

function add(world, geometry, material) {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function byId(data, id) {
  return data.blockers.find((item) => item.id === id)
}

function footprint(data, id) {
  const item = byId(data, id)
  return item ? item.renderFootprint ?? item.sourceFootprint : null
}

function addBedPolish(world, data) {
  const f = footprint(data, 'bedroom.bed')
  if (!f) return

  // A muted runner breaks up the very pale mattress from the equally pale shell.
  add(world, boxGeometry(
    f.x + f.w * 0.66,
    f.y + f.h * 0.07,
    f.w * 0.20,
    f.h * 0.86,
    84.6,
    87.1,
  ), materials.bedRunner)

  // Keep the accepted west-side headboard envelope but give its visible face
  // a stronger warm value so the bed reads through the cutaway at rest.
  add(world, boxGeometry(
    f.x + f.w * 0.004,
    f.y + f.h * 0.045,
    Math.max(3.5, f.w * 0.028),
    f.h * 0.91,
    43,
    150,
  ), materials.headboardFace)
}

function addWhiteChairPolish(world, data) {
  const f = footprint(data, 'living.white_chair')
  if (!f) return

  add(world, ellipsoidGeometry(
    f.x + f.w * 0.14,
    f.y + f.h * 0.14,
    f.w * 0.72,
    f.h * 0.67,
    54,
    68,
  ), materials.chairInset)

  add(world, ellipsoidGeometry(
    f.x + f.w * 0.12,
    f.y + f.h * 0.015,
    f.w * 0.76,
    f.h * 0.46,
    67,
    94,
  ), materials.chairEdge)
}

function addKitchenPolish(world, data) {
  const island = footprint(data, 'kitchen.island')
  if (island) {
    add(world, boxGeometry(
      island.x + island.w * 0.04,
      island.y + island.h * 0.035,
      island.w * 0.92,
      Math.max(3.0, island.h * 0.018),
      5,
      14,
    ), materials.cabinetKick)
  }

  const run = footprint(data, 'kitchen.cabinet_run')
  if (run) {
    for (const ratio of [0.17, 0.35, 0.53, 0.71]) {
      add(world, boxGeometry(
        run.x + run.w * 0.03,
        run.y + run.h * ratio,
        run.w * 0.94,
        Math.max(1.6, run.h * 0.004),
        20,
        112,
      ), materials.cabinetSeam)
    }
  }
}

function addServicePolish(world, data) {
  for (const id of ['bath.vanity', 'service.laundry', 'closet.dresser']) {
    const f = footprint(data, id)
    if (!f) continue
    add(world, boxGeometry(
      f.x + f.w * 0.035,
      f.y + f.h * 0.035,
      Math.max(2.5, f.w * 0.055),
      f.h * 0.93,
      18,
      Math.min(116, id === 'service.laundry' ? 105 : 112),
    ), materials.serviceFace)
  }
}

export function addApartmentStaticPolishV1(world, data) {
  addApartmentDetailsV1(world, data)
  // bedroom-v1.js owns the Braya frame and bedding replacement.
  addKitchenPolish(world, data)
  addServicePolish(world, data)
}
