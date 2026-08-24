import * as THREE from 'three'
import { addApartmentFurnitureIdentity } from './furniture-v1.js'

const materials = Object.freeze({
  beddingTop: new THREE.MeshStandardMaterial({ color: 0xe7e1d7, roughness: 0.99 }),
  pillow: new THREE.MeshStandardMaterial({ color: 0xf0ece4, roughness: 1 }),
  couchCushion: new THREE.MeshStandardMaterial({ color: 0x8b6954, roughness: 0.98 }),
  couchBack: new THREE.MeshStandardMaterial({ color: 0x76533f, roughness: 0.98 }),
  whiteChairInset: new THREE.MeshStandardMaterial({ color: 0xcfc6ba, roughness: 0.98 }),
  whiteChairBase: new THREE.MeshStandardMaterial({ color: 0x4b4e4c, roughness: 0.78, metalness: 0.04 }),
  deskTop: new THREE.MeshStandardMaterial({ color: 0x423f3a, roughness: 0.82 }),
  deskMetal: new THREE.MeshStandardMaterial({ color: 0x2c2f2e, roughness: 0.72, metalness: 0.08 }),
  coffeeTop: new THREE.MeshStandardMaterial({ color: 0x8a7158, roughness: 0.9 }),
  mediaInset: new THREE.MeshStandardMaterial({ color: 0x242726, roughness: 0.76 }),
  speakerGrille: new THREE.MeshStandardMaterial({ color: 0x1e2221, roughness: 0.96 }),
  cabinetShadow: new THREE.MeshStandardMaterial({ color: 0xc9c5bc, roughness: 0.92 }),
  cabinetRail: new THREE.MeshStandardMaterial({ color: 0xd6d2c9, roughness: 0.9 }),
  backsplash: new THREE.MeshStandardMaterial({ color: 0xb5b0a7, roughness: 0.88 }),
  stoolSeat: new THREE.MeshStandardMaterial({ color: 0x5a5b57, roughness: 0.94 }),
  serviceInset: new THREE.MeshStandardMaterial({ color: 0xbfc2bf, roughness: 0.86 }),
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

function ellipsoidGeometry(x, y, w, h, zMin, zMax, segments = 24) {
  const radiusZ = (zMax - zMin) / 2
  const geometry = new THREE.SphereGeometry(1, segments, Math.max(12, Math.round(segments * 0.66)))
  geometry.scale(w / 2, h / 2, radiusZ)
  geometry.translate(x + w / 2, y + h / 2, zMin + radiusZ)
  return geometry
}

function add(world, geometry, material, { castShadow = true, receiveShadow = true } = {}) {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = castShadow
  mesh.receiveShadow = receiveShadow
  world.add(mesh)
  return mesh
}

function footprint(blocker) {
  return blocker.renderFootprint ?? blocker.sourceFootprint
}

function byId(data, id) {
  return data.blockers.find((blocker) => blocker.id === id)
}

function addBedIdentity(world, data) {
  const blocker = byId(data, 'bedroom.bed')
  if (!blocker) return
  const f = footprint(blocker)

  // Headboard is on the west/x-min side. Keep all soft detail inside the
  // already accepted bed envelope.
  add(world, boxGeometry(
    f.x + f.w * 0.28,
    f.y + f.h * 0.055,
    f.w * 0.66,
    f.h * 0.89,
    78.2,
    84.5,
  ), materials.beddingTop)

  const pillowX = f.x + f.w * 0.105
  const pillowW = f.w * 0.205
  for (const y of [f.y + f.h * 0.105, f.y + f.h * 0.545]) {
    add(world, ellipsoidGeometry(
      pillowX,
      y,
      pillowW,
      f.h * 0.31,
      78.5,
      94,
    ), materials.pillow)
  }
}

function addCouchIdentity(world, data) {
  const blocker = byId(data, 'living.couch')
  if (!blocker) return
  const f = footprint(blocker)

  // Sofa length runs along Y; three loose cushions make the 92in sofa read
  // from the fixed hero camera without changing its accepted footprint.
  const seatX = f.x + f.w * 0.075
  const seatW = f.w * 0.625
  const segmentGap = f.h * 0.018
  const segmentH = (f.h * 0.82 - segmentGap * 2) / 3
  const firstY = f.y + f.h * 0.09

  for (let index = 0; index < 3; index += 1) {
    const y = firstY + index * (segmentH + segmentGap)
    add(world, ellipsoidGeometry(
      seatX,
      y,
      seatW,
      segmentH,
      63.8,
      73.2,
      20,
    ), materials.couchCushion)

    add(world, ellipsoidGeometry(
      f.x + f.w * 0.57,
      y + segmentH * 0.04,
      f.w * 0.235,
      segmentH * 0.92,
      70,
      105,
      20,
    ), materials.couchBack)
  }
}

function addWhiteChairIdentity(world, data) {
  const blocker = byId(data, 'living.white_chair')
  if (!blocker) return
  const f = footprint(blocker)

  const baseRadius = Math.min(f.w, f.h) * 0.16
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(baseRadius, baseRadius * 1.12, 12, 24),
    materials.whiteChairBase,
  )
  base.rotation.x = Math.PI / 2
  base.position.set(f.x + f.w / 2, f.y + f.h / 2, 10)
  base.castShadow = true
  base.receiveShadow = true
  world.add(base)

  add(world, ellipsoidGeometry(
    f.x + f.w * 0.205,
    f.y + f.h * 0.31,
    f.w * 0.59,
    f.h * 0.45,
    56,
    66,
  ), materials.whiteChairInset)
}

function addDeskIdentity(world, data) {
  const main = byId(data, 'bedroom.desk_main')
  const deskReturn = byId(data, 'bedroom.desk_return')
  if (!main || !deskReturn) return

  for (const blocker of [main, deskReturn]) {
    const f = footprint(blocker)
    add(world, boxGeometry(f.x, f.y, f.w, f.h, 100.2, 103.5), materials.deskTop)
  }

  // Tiny bridge closes any sub-pixel seam between the two accepted desk
  // footprints while staying entirely inside their union.
  const a = footprint(main)
  const b = footprint(deskReturn)
  const bridge = 5
  add(world, boxGeometry(
    Math.max(b.x, a.x - bridge),
    Math.max(a.y, b.y + b.h - bridge),
    Math.min(bridge, a.w),
    Math.min(bridge, b.h),
    100.2,
    103.5,
  ), materials.deskTop)

  const monitor = byId(data, 'bedroom.monitor')
  if (monitor) {
    const f = footprint(monitor)
    const cx = f.x + f.w / 2
    const cy = f.y + f.h / 2
    add(world, boxGeometry(cx - 4, cy - 4, 8, 8, 63, 70), materials.deskMetal)
    add(world, boxGeometry(cx - f.w * 0.18, cy - f.h * 0.25, f.w * 0.36, f.h * 0.5, 61, 64), materials.deskMetal)
  }
}

function addCoffeeTableIdentity(world, data) {
  const blocker = byId(data, 'living.coffee_table')
  if (!blocker) return
  const f = footprint(blocker)
  add(world, boxGeometry(
    f.x + f.w * 0.035,
    f.y + f.h * 0.025,
    f.w * 0.93,
    f.h * 0.95,
    60.9,
    64.2,
  ), materials.coffeeTop)
}

function addMediaIdentity(world, data) {
  const stand = byId(data, 'living.tv_stand')
  if (stand) {
    const f = footprint(stand)
    add(world, boxGeometry(f.x, f.y, f.w, f.h, 135.6, 139.8), materials.mediaInset)

    // Two shallow front divisions give the low black console a readable
    // cabinet rhythm from the hero angle without guessing internal hardware.
    const division = Math.max(2, f.h * 0.018)
    for (const offset of [0.34, 0.67]) {
      add(world, boxGeometry(
        f.x,
        f.y + f.h * offset - division / 2,
        Math.min(4, f.w * 0.08),
        division,
        18,
        118,
      ), materials.mediaInset)
    }
  }

  const sub = byId(data, 'living.subwoofer')
  if (sub) {
    const f = footprint(sub)
    add(world, boxGeometry(
      f.x + f.w * 0.06,
      f.y + f.h * 0.06,
      f.w * 0.88,
      f.h * 0.88,
      51.9,
      53.3,
    ), materials.speakerGrille)
  }
}

function addKitchenIdentity(world, data) {
  // The upper boxes in v1 are deliberately simple; these rails/backing cues
  // visually tie them into one wall-mounted kitchen composition.
  add(world, boxGeometry(972.5, 718.52, 8, 399.17, 122.1, 184), materials.backsplash)
  add(world, boxGeometry(936.43, 718.52, 44.07, 399.17, 325.4, 331.5), materials.cabinetRail)

  for (const id of ['kitchen.stool_1', 'kitchen.stool_2']) {
    const stool = byId(data, id)
    if (!stool) continue
    const f = footprint(stool)
    add(world, ellipsoidGeometry(
      f.x + f.w * 0.08,
      f.y + f.h * 0.06,
      f.w * 0.84,
      f.h * 0.88,
      86.5,
      91.2,
      18,
    ), materials.stoolSeat)
  }

  const fridge = byId(data, 'kitchen.fridge')
  if (fridge) {
    const f = footprint(fridge)
    const split = f.y + f.h * 0.56
    add(world, boxGeometry(f.x, split - 1.1, f.w, 2.2, 18, 211), materials.cabinetShadow)
  }
}

function addServiceIdentity(world, data) {
  const laundry = byId(data, 'service.laundry')
  if (!laundry) return
  const f = footprint(laundry)

  // Shallow face bands distinguish washer/dryer modules from surrounding
  // white architecture without turning the service zone into a focal point.
  for (const z of [43, 177]) {
    add(world, boxGeometry(
      f.x + f.w * 0.08,
      f.y + f.h * 0.04,
      f.w * 0.84,
      Math.max(2.5, f.h * 0.05),
      z,
      z + 3.4,
    ), materials.serviceInset)
  }
}

export function addApartmentFurnitureIdentityV2(world, data) {
  addApartmentFurnitureIdentity(world, data)
  addBedIdentity(world, data)
  addCouchIdentity(world, data)
  addWhiteChairIdentity(world, data)
  addDeskIdentity(world, data)
  addCoffeeTableIdentity(world, data)
  addMediaIdentity(world, data)
  addKitchenIdentity(world, data)
  addServiceIdentity(world, data)
}
