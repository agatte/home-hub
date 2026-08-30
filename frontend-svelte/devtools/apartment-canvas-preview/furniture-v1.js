import * as THREE from 'three'

const palette = Object.freeze({
  carpet: 0xb9b1a4,
  rug: 0x8f887b,
  runner: 0x8b9290,
  bedFrame: 0x6f6257,
  bedding: 0xd9d2c8,
  desk: 0x363634,
  chair: 0xe2ddd4,
  chairBase: 0x4a4a47,
  couch: 0x7a5844,
  couchSeat: 0x85634e,
  coffeeWood: 0x7b654f,
  coffeeFrame: 0x343735,
  whiteChair: 0xe4dfd6,
  media: 0x2d302f,
  endTable: 0x6b5948,
  speaker: 0x2f3231,
  alexa: 0x5c6260,
  cabinet: 0xe1ded5,
  counter: 0xb9b4aa,
  darkCounter: 0x72736f,
  stool: 0x494b49,
  steel: 0xa6aaa6,
  applianceDark: 0x454947,
  bathroom: 0xe3e1da,
  bathroomDark: 0x767b78,
  service: 0xd8d9d5,
  dresser: 0x7a644f,
  screen: 0x202322,
  projector: 0xdeddd8,
})

function mat(color, roughness = 0.88, metalness = 0) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness })
}

const materials = Object.freeze({
  carpet: mat(palette.carpet, 1),
  rug: mat(palette.rug, 0.98),
  runner: mat(palette.runner, 0.98),
  bedFrame: mat(palette.bedFrame, 0.92),
  bedding: mat(palette.bedding, 0.98),
  desk: mat(palette.desk, 0.84),
  chair: mat(palette.chair, 0.96),
  chairBase: mat(palette.chairBase, 0.78, 0.05),
  couch: mat(palette.couch, 0.96),
  couchSeat: mat(palette.couchSeat, 0.97),
  coffeeWood: mat(palette.coffeeWood, 0.88),
  coffeeFrame: mat(palette.coffeeFrame, 0.7, 0.08),
  whiteChair: mat(palette.whiteChair, 0.97),
  media: mat(palette.media, 0.74, 0.04),
  endTable: mat(palette.endTable, 0.9),
  speaker: mat(palette.speaker, 0.93),
  alexa: mat(palette.alexa, 0.82),
  cabinet: mat(palette.cabinet, 0.9),
  counter: mat(palette.counter, 0.72),
  darkCounter: mat(palette.darkCounter, 0.74),
  stool: mat(palette.stool, 0.86),
  steel: mat(palette.steel, 0.5, 0.32),
  applianceDark: mat(palette.applianceDark, 0.6, 0.1),
  bathroom: mat(palette.bathroom, 0.92),
  bathroomDark: mat(palette.bathroomDark, 0.72, 0.08),
  service: mat(palette.service, 0.88),
  dresser: mat(palette.dresser, 0.9),
  screen: mat(palette.screen, 0.58, 0.02),
  projector: mat(palette.projector, 0.82),
})

// Presentation-only bedroom carpet coverage. It deliberately reaches beneath
// the north window/sill host plane so the shared apartment slab cannot show as
// hardwood inside the carpeted room. It does not alter any physical geometry.
export const BEDROOM_CARPET_COVERAGE_V1 = Object.freeze({ x: 9.8, y: 46.38, w: 413.5, h: 488.22 })

function shapeFromRing(ring) {
  const shape = new THREE.Shape()
  shape.moveTo(ring[0].x, ring[0].y)
  ring.slice(1).forEach((point) => shape.lineTo(point.x, point.y))
  shape.closePath()
  return shape
}

function extrudeRing(ring, zMin, zMax) {
  const geometry = new THREE.ExtrudeGeometry(shapeFromRing(ring), {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 1,
  })
  geometry.translate(0, 0, zMin)
  return geometry
}

function rectRing(x, y, w, h) {
  return [
    { x, y },
    { x: x + w, y },
    { x: x + w, y: y + h },
    { x, y: y + h },
  ]
}

function ellipseGeometry(x, y, w, h, zMin, zMax) {
  const shape = new THREE.Shape()
  shape.absellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, Math.PI * 2, false, 0)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 24,
  })
  geometry.translate(0, 0, zMin)
  return geometry
}

function primitiveBounds(footprint, primitive) {
  return {
    x: footprint.x + footprint.w * (primitive.x ?? 0),
    y: footprint.y + footprint.h * (primitive.y ?? 0),
    w: footprint.w * (primitive.w ?? 1),
    h: footprint.h * (primitive.h ?? 1),
  }
}

function materialFor(blocker, primitive) {
  const id = blocker.id
  const name = primitive.name.toLowerCase()

  if (id === 'bedroom.bed') return name.includes('mattress') ? materials.bedding : materials.bedFrame
  if (id.startsWith('bedroom.desk_')) return materials.desk
  if (id === 'bedroom.chair') return name.includes('pedestal') || name.includes('caster') ? materials.chairBase : materials.chair
  if (id === 'bedroom.monitor' || id === 'bedroom.pc') return materials.screen
  if (id === 'bedroom.projector') return materials.projector

  if (id === 'living.couch') return name.includes('seat') ? materials.couchSeat : materials.couch
  if (id === 'living.coffee_table') return name.includes('tabletop') ? materials.coffeeWood : materials.coffeeFrame
  if (id === 'living.white_chair') return materials.whiteChair
  if (id === 'living.tv_stand' || id === 'living.tv' || id === 'living.subwoofer') return materials.media
  if (id === 'living.end_table_cluster') return materials.endTable

  if (id === 'kitchen.island' || id === 'kitchen.cabinet_run' || id === 'kitchen.pantry') {
    return name.includes('counter') || name.includes('worktop') ? materials.counter : materials.cabinet
  }
  if (id.startsWith('kitchen.stool_')) return materials.stool
  if (id === 'kitchen.stove') return name.includes('cooktop') ? materials.applianceDark : materials.steel
  if (id === 'kitchen.fridge' || id === 'kitchen.microwave') return materials.steel

  if (id === 'bath.vanity') return name.includes('counter') ? materials.counter : materials.cabinet
  if (id === 'bath.toilet') return materials.bathroom
  if (id === 'bath.shower') return name.includes('pan') ? materials.bathroom : materials.bathroomDark
  if (id.startsWith('service.')) return materials.service
  if (id === 'entry.dresser' || id === 'closet.dresser') return materials.dresser

  return materials.cabinet
}

function addMesh(world, geometry, material) {
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
  return mesh
}

function addPrimitive(world, blocker, primitive) {
  const footprint = blocker.renderFootprint ?? blocker.sourceFootprint
  const material = materialFor(blocker, primitive)

  const addPart = (part) => {
    const bounds = primitiveBounds(footprint, part)
    if (part.kind === 'ellipse') {
      return addMesh(world, ellipseGeometry(bounds.x, bounds.y, bounds.w, bounds.h, part.zMin, part.zMax), material)
    }
    if (part.kind === 'ellipsoid') {
      const radiusZ = (part.zMax - part.zMin) / 2
      const geometry = new THREE.SphereGeometry(1, 24, 16)
      geometry.scale(bounds.w / 2, bounds.h / 2, radiusZ)
      geometry.translate(bounds.x + bounds.w / 2, bounds.y + bounds.h / 2, part.zMin + radiusZ)
      return addMesh(world, geometry, material)
    }
    return addMesh(world, extrudeRing(rectRing(bounds.x, bounds.y, bounds.w, bounds.h), part.zMin, part.zMax), material)
  }

  if (primitive.kind !== 'open_frame') {
    addPart(primitive)
    return
  }

  const t = primitive.thickness
  for (const rail of [
    { kind: 'box', name: `${primitive.name} west rail`, x: 0, y: 0, w: t, h: 1, zMin: primitive.zMin, zMax: primitive.zMax },
    { kind: 'box', name: `${primitive.name} east rail`, x: 1 - t, y: 0, w: t, h: 1, zMin: primitive.zMin, zMax: primitive.zMax },
    { kind: 'box', name: `${primitive.name} north rail`, x: 0, y: 1 - t, w: 1, h: t, zMin: primitive.zMin, zMax: primitive.zMax },
  ]) addPart(rail)
}

function addSoftFloor(world, bounds, material, zMin = 0.7, zMax = 1.35) {
  addMesh(world, extrudeRing(rectRing(bounds.x, bounds.y, bounds.w, bounds.h), zMin, zMax), material)
}

function addEndTableDevices(world, blocker) {
  const f = blocker.renderFootprint ?? blocker.sourceFootprint
  const alexaRadius = Math.min(f.w, f.h) * 0.14
  const alexa = new THREE.Mesh(
    new THREE.CylinderGeometry(alexaRadius, alexaRadius, 8, 24),
    materials.alexa,
  )
  alexa.rotation.x = Math.PI / 2
  alexa.position.set(f.x + f.w * 0.52, f.y + f.h * 0.48, 87)
  alexa.castShadow = true
  world.add(alexa)

  const sonosW = f.w * 0.56
  const sonosH = f.h * 0.36
  addMesh(world, extrudeRing(rectRing(
    f.x + (f.w - sonosW) / 2,
    f.y + (f.h - sonosH) / 2,
    sonosW,
    sonosH,
  ), 18, 53), materials.speaker)
}

function addUpperKitchenCabinets(world) {
  const cabinets = [
    { x: 936.43, y: 718.52, w: 44.07, h: 81.36, zMin: 183.91, zMax: 326.29 },
    { x: 936.43, y: 803.27, w: 44.07, h: 100.01, zMin: 246.62, zMax: 326.29 },
    { x: 936.43, y: 903.28, w: 44.07, h: 91.53, zMin: 183.91, zMax: 326.29 },
    { x: 936.43, y: 995.65, w: 44.07, h: 122.04, zMin: 246.62, zMax: 326.29 },
  ]
  for (const cabinet of cabinets) {
    addMesh(world, extrudeRing(rectRing(cabinet.x, cabinet.y, cabinet.w, cabinet.h), cabinet.zMin, cabinet.zMax), materials.cabinet)
  }
}

function addKitchenSinkCue(world, island) {
  const f = island.renderFootprint ?? island.sourceFootprint
  const w = f.w * 0.42
  const h = f.h * 0.19
  addMesh(world, extrudeRing(rectRing(
    f.x + f.w * 0.29,
    f.y + f.h * 0.14,
    w,
    h,
  ), 122.08, 124.2), materials.applianceDark)
}

export function addApartmentFurnitureIdentity(world, data) {
  // Approved bedroom interior faces from the deterministic top-down geometry.
  // This is a presentation-only surface and does not alter the underlying slab.
  // Overlap beneath the room walls by a few GU so the apartment hardwood
  // cannot peek through as a false border along the bedroom edges.
  addSoftFloor(world, BEDROOM_CARPET_COVERAGE_V1, materials.carpet)

  // Low-detail floor textiles: identity and room zoning, not texture recreation.
  addSoftFloor(world, { x: 580.00, y: 234.34, w: 244.08, h: 366.12 }, materials.rug, 0.72, 1.22)
  addSoftFloor(world, { x: 790.07, y: 840.52, w: 65.09, h: 280.72 }, materials.runner, 0.72, 1.22)

  for (const blocker of data.blockers) {
    // Bedroom workstation identity is deliberately owned by bedroom-v1.js.
    // The accepted blocker footprints remain data anchors, but rendering their
    // generic primitives here would leave duplicate desk, chair, and monitor
    // geometry underneath the faithful replacements.
    if ([
      'bedroom.bed', 'bedroom.desk_main', 'bedroom.desk_return', 'bedroom.chair',
      'bedroom.monitor', 'bedroom.pc', 'bedroom.projector', 'living.couch',
      // These Living Room objects retain their GeometryScene compatibility
      // anchors, but their visual identity is owned by
      // living-room-furniture-v1.js. Do not draw generic primitives beneath
      // their bounded replacements.
      'living.coffee_table', 'living.white_chair',
    ].includes(blocker.id)) continue

    // End table becomes an open cluster rather than a solid whitebox mass.
    if (blocker.id === 'living.end_table_cluster') {
      const f = blocker.renderFootprint ?? blocker.sourceFootprint
      const top = 83.06
      const leg = 0.08
      const shelf = 4
      for (const bounds of [
        { x: f.x, y: f.y, w: f.w, h: f.h, zMin: top - shelf, zMax: top },
        { x: f.x, y: f.y, w: f.w, h: f.h, zMin: 7, zMax: 7 + shelf },
        { x: f.x, y: f.y, w: f.w * leg, h: f.h * leg, zMin: 0, zMax: top },
        { x: f.x + f.w * (1 - leg), y: f.y, w: f.w * leg, h: f.h * leg, zMin: 0, zMax: top },
        { x: f.x, y: f.y + f.h * (1 - leg), w: f.w * leg, h: f.h * leg, zMin: 0, zMax: top },
        { x: f.x + f.w * (1 - leg), y: f.y + f.h * (1 - leg), w: f.w * leg, h: f.h * leg, zMin: 0, zMax: top },
      ]) addMesh(world, extrudeRing(rectRing(bounds.x, bounds.y, bounds.w, bounds.h), bounds.zMin, bounds.zMax), materials.endTable)
      addEndTableDevices(world, blocker)
      continue
    }

    blocker.primitives.forEach((primitive) => addPrimitive(world, blocker, primitive))
  }

  addUpperKitchenCabinets(world)
  const island = data.blockers.find((blocker) => blocker.id === 'kitchen.island')
  if (island) addKitchenSinkCue(world, island)
}
