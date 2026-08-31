import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { parseRational } from '../apartment-whitebox/adapter.js'
import { addApartmentFurnitureIdentityV2 } from './furniture-v2.js'

const materials = Object.freeze({
  lampDark: new THREE.MeshStandardMaterial({ color: 0x42413d, roughness: 0.82, metalness: 0.05 }),
  lampLight: new THREE.MeshStandardMaterial({ color: 0xd8d1c4, roughness: 0.9 }),
  lampGlass: new THREE.MeshPhysicalMaterial({ color: 0xc7d2cf, roughness: 0.08, transmission: 0.35, transparent: true, opacity: 0.35 }),
  mic: new THREE.MeshStandardMaterial({ color: 0x242727, roughness: 0.72, metalness: 0.08 }),
  headphones: new THREE.MeshStandardMaterial({ color: 0x2c2f2f, roughness: 0.78, metalness: 0.04 }),
  alexa: new THREE.MeshStandardMaterial({ color: 0x555b59, roughness: 0.82 }),
  plantPot: new THREE.MeshStandardMaterial({ color: 0x9c8a79, roughness: 0.96 }),
  plantStand: new THREE.MeshStandardMaterial({ color: 0x6e6257, roughness: 0.88 }),
  snake: new THREE.MeshStandardMaterial({ color: 0x526b50, roughness: 0.98 }),
  zzStem: new THREE.MeshStandardMaterial({ color: 0x435d42, roughness: 0.98 }),
  zzLeaf: new THREE.MeshStandardMaterial({ color: 0x5c7657, roughness: 0.98 }),
  deskEdge: new THREE.MeshStandardMaterial({ color: 0x272a29, roughness: 0.75, metalness: 0.04 }),
})

function add(world, geometry, material, { castShadow = true, receiveShadow = true } = {}) {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = castShadow
  mesh.receiveShadow = receiveShadow
  world.add(mesh)
  return mesh
}

function boxGeometry(x, y, w, h, zMin, zMax) {
  const shape = new THREE.Shape()
  shape.moveTo(x, y)
  shape.lineTo(x + w, y)
  shape.lineTo(x + w, y + h)
  shape.lineTo(x, y + h)
  shape.closePath()
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 1,
  })
  geometry.translate(0, 0, zMin)
  return geometry
}

function ellipsoidGeometry(x, y, w, h, zMin, zMax, segments = 20) {
  const radiusZ = (zMax - zMin) / 2
  const geometry = new THREE.SphereGeometry(1, segments, Math.max(10, Math.round(segments * 0.7)))
  geometry.scale(w / 2, h / 2, radiusZ)
  geometry.translate(x + w / 2, y + h / 2, zMin + radiusZ)
  return geometry
}

function cylinder(world, x, y, zMin, zMax, radius, material, radialSegments = 18) {
  const height = zMax - zMin
  const geometry = new THREE.CylinderGeometry(radius, radius, height, radialSegments)
  geometry.rotateX(Math.PI / 2)
  geometry.translate(x, y, zMin + height / 2)
  return add(world, geometry, material)
}

function cone(world, x, y, zMin, zMax, radius, material, radialSegments = 6) {
  const height = zMax - zMin
  const geometry = new THREE.ConeGeometry(radius, height, radialSegments)
  geometry.rotateX(Math.PI / 2)
  geometry.translate(x, y, zMin + height / 2)
  return add(world, geometry, material)
}

function rawObjectRect(id) {
  const item = geometryScene.inspection_annotations.objects.find((object) => object.id === id)
  if (!item?.rect_gu) return null
  return Object.fromEntries(Object.entries(item.rect_gu).map(([key, token]) => [key, parseRational(token)]))
}

function blocker(data, id) {
  return data.blockers.find((item) => item.id === id)
}

function blockerFootprint(data, id) {
  const item = blocker(data, id)
  return item ? item.renderFootprint ?? item.sourceFootprint : null
}

function addDeskEdgeIdentity(world, data) {
  for (const id of ['bedroom.desk_main', 'bedroom.desk_return']) {
    const f = blockerFootprint(data, id)
    if (!f) continue
    const edge = Math.min(4.2, Math.max(2.4, Math.min(f.w, f.h) * 0.08))
    add(world, boxGeometry(f.x, f.y, f.w, edge, 100.4, 104.2), materials.deskEdge)
  }
}

function addBedroomLamp(world, id, variant) {
  const f = rawObjectRect(id)
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const baseRadius = Math.min(f.w, f.h) * 0.30

  cylinder(world, cx, cy, 103.8, 109.5, baseRadius, materials.lampDark)

  if (variant === 'clear') {
    cylinder(world, cx, cy, 109.5, 143, baseRadius * 0.82, materials.lampGlass, 20)
    cylinder(world, cx, cy, 109.5, 145.5, Math.max(1.2, baseRadius * 0.10), materials.lampDark, 12)
    cone(world, cx, cy, 141, 165, baseRadius * 1.15, materials.lampLight, 16)
  } else {
    cylinder(world, cx, cy, 109.5, 146, Math.max(1.3, baseRadius * 0.11), materials.lampDark, 12)
    cone(world, cx, cy, 137, 164, baseRadius * 1.30, materials.lampLight, 6)
  }
}

function addDeskMicrophone(world) {
  const f = rawObjectRect('bedroom.microphone')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  cylinder(world, cx, cy, 104, 108, Math.max(2.1, f.w * 0.24), materials.mic, 14)
  cylinder(world, cx, cy, 108, 135, Math.max(1.6, f.w * 0.17), materials.mic, 14)
  add(world, ellipsoidGeometry(cx - f.w * 0.28, cy - f.h * 0.24, f.w * 0.56, f.h * 0.48, 132, 146, 18), materials.mic)
}

function addDeskHeadphones(world) {
  const f = rawObjectRect('bedroom.headphones')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const radius = Math.min(f.w, f.h) * 0.32
  const tube = Math.max(0.9, radius * 0.18)
  const torus = new THREE.TorusGeometry(radius, tube, 8, 24)
  torus.translate(cx, cy, 106)
  add(world, torus, materials.headphones)
  cylinder(world, cx - radius * 0.82, cy, 104.5, 109.5, tube * 1.45, materials.headphones, 12)
  cylinder(world, cx + radius * 0.82, cy, 104.5, 109.5, tube * 1.45, materials.headphones, 12)
}

function addDeskAlexa(world) {
  const f = rawObjectRect('bedroom.alexa')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const radius = Math.min(f.w, f.h) * 0.30
  cylinder(world, cx, cy, 104, 111, radius, materials.alexa, 24)
}

function addPlantStand(world, x, y, w, h, topZ) {
  const t = Math.max(1.5, Math.min(w, h) * 0.065)
  for (const [px, py] of [
    [x + t, y + t],
    [x + w - t, y + t],
    [x + t, y + h - t],
    [x + w - t, y + h - t],
  ]) cylinder(world, px, py, 2, topZ, t * 0.55, materials.plantStand, 10)
  add(world, boxGeometry(x, y, w, h, topZ - 2.4, topZ), materials.plantStand)
}

function addPlantPot(world, x, y, w, h, zMin, zMax) {
  const radius = Math.min(w, h) * 0.30
  const cx = x + w / 2
  const cy = y + h / 2
  cylinder(world, cx, cy, zMin, zMax, radius, materials.plantPot, 18)
  return { cx, cy, radius }
}

function addSnakePlant(world, data) {
  const couch = blockerFootprint(data, 'living.couch')
  if (!couch) return
  const x = 917.45
  const y = couch.y + couch.h + 40.68
  const w = 33.36
  const h = 33.36
  const standTop = 93.39
  addPlantStand(world, x, y, w, h, standTop)
  const { cx, cy, radius } = addPlantPot(world, x, y, w, h, standTop, 119.16)

  const leaves = [
    [-0.42, -0.10, 62], [-0.24, 0.20, 74], [-0.05, -0.18, 84],
    [0.10, 0.18, 71], [0.28, -0.10, 79], [0.42, 0.14, 66], [0.02, 0.02, 91],
  ]
  for (const [ox, oy, height] of leaves) {
    cone(world,
      cx + radius * ox,
      cy + radius * oy,
      115,
      115 + height,
      Math.max(2.0, radius * 0.12),
      materials.snake,
      5,
    )
  }
}

function addZZPlant(world, data) {
  const couch = blockerFootprint(data, 'living.couch')
  if (!couch) return
  const x = 865.24
  const y = couch.y + couch.h + 23.73
  const w = 29.36
  const h = 29.36
  const standTop = 80.07
  addPlantStand(world, x, y, w, h, standTop)
  const { cx, cy, radius } = addPlantPot(world, x, y, w, h, standTop, 104.71)

  const stems = [
    { ox: -0.28, oy: -0.12, top: 150 },
    { ox: -0.06, oy: 0.18, top: 170 },
    { ox: 0.18, oy: -0.16, top: 158 },
    { ox: 0.30, oy: 0.16, top: 145 },
  ]
  for (const stem of stems) {
    const sx = cx + radius * stem.ox
    const sy = cy + radius * stem.oy
    cylinder(world, sx, sy, 102, stem.top, 1.35, materials.zzStem, 10)
    const leafLevels = [0.42, 0.62, 0.80]
    for (const [index, ratio] of leafLevels.entries()) {
      const z = 102 + (stem.top - 102) * ratio
      const spread = radius * (0.36 + index * 0.04)
      add(world, ellipsoidGeometry(sx - spread - 3.2, sy - 2.1, 7.2, 4.5, z - 2.0, z + 2.0, 14), materials.zzLeaf)
      add(world, ellipsoidGeometry(sx + spread - 4.0, sy + 0.5, 7.2, 4.5, z - 2.0, z + 2.0, 14), materials.zzLeaf)
    }
  }
}

export function addApartmentDetailsV1(world, data) {
  addApartmentFurnitureIdentityV2(world, data)
  // The workstation's desk edge, lamps, and microphone are faithfully owned
  // by bedroom-v1.js. Its headphones and Alexa are fixed world-space groups,
  // so do not retain the old generic ring or loose cylinder underneath.
  addSnakePlant(world, data)
  addZZPlant(world, data)
  // living-room-media-v1.js owns the TV, console, and subwoofer replacement.
}
