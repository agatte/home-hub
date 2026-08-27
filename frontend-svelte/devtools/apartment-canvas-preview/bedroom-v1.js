import * as THREE from 'three'
import { resolveBedroomPhysicalWorld } from './physical-world-v1.js'
import { resolveBurgenerDeskStructure } from './burgener-desk-v1.js'
import { resolveBedroomWorkstationAccessories } from './workstation-accessories-v1.js'

const bedroomPhysical = resolveBedroomPhysicalWorld()
const workstationAccessories = resolveBedroomWorkstationAccessories(bedroomPhysical)

// Bounded workstation identity layer. It consumes accepted footprints only;
// it never changes plan geometry, cutaways, reflection, or Camera v2.
const m = Object.freeze({
  top: new THREE.MeshStandardMaterial({ color: 0x938778, roughness: 0.84 }),
  grain: new THREE.MeshStandardMaterial({ color: 0x71695e, roughness: 0.91 }),
  grainLight: new THREE.MeshStandardMaterial({ color: 0xa79a89, roughness: 0.9 }),
  black: new THREE.MeshStandardMaterial({ color: 0x1f211f, roughness: 0.64, metalness: 0.08 }),
  steel: new THREE.MeshStandardMaterial({ color: 0x171a19, roughness: 0.44, metalness: 0.58 }),
  cabinet: new THREE.MeshStandardMaterial({ color: 0x20221f, roughness: 0.77, metalness: 0.03 }),
  face: new THREE.MeshStandardMaterial({ color: 0x9a8b79, roughness: 0.85 }),
  void: new THREE.MeshStandardMaterial({ color: 0x141716, roughness: 0.9 }),
  white: new THREE.MeshStandardMaterial({ color: 0xf0eee7, roughness: 0.72 }),
  stitch: new THREE.MeshStandardMaterial({ color: 0xd5d0c7, roughness: 0.9 }),
  chrome: new THREE.MeshStandardMaterial({ color: 0xb9c0bf, roughness: 0.25, metalness: 0.86 }),
  caster: new THREE.MeshStandardMaterial({ color: 0x222525, roughness: 0.68, metalness: 0.13 }),
  monitor: new THREE.MeshStandardMaterial({ color: 0x151918, roughness: 0.43, metalness: 0.2 }),
  display: new THREE.MeshStandardMaterial({ color: 0x1a2c2a, roughness: 0.26, emissive: 0x071411, emissiveIntensity: 0.28 }),
  displayEdge: new THREE.MeshStandardMaterial({ color: 0x090b0b, roughness: 0.36, metalness: 0.24 }),
  mic: new THREE.MeshStandardMaterial({ color: 0x171a1a, roughness: 0.54, metalness: 0.28 }),
  grille: new THREE.MeshStandardMaterial({ color: 0x2e3433, roughness: 0.4, metalness: 0.56 }),
  micControl: new THREE.MeshStandardMaterial({ color: 0x565d5b, roughness: 0.34, metalness: 0.42 }),
  cream: new THREE.MeshStandardMaterial({ color: 0xd8cfbd, roughness: 0.91 }),
  lampLinen: new THREE.MeshStandardMaterial({ color: 0xcfc2a6, roughness: 0.98, metalness: 0, side: THREE.DoubleSide }),
  trim: new THREE.MeshStandardMaterial({ color: 0x343736, roughness: 0.58, metalness: 0.18 }),
  stone: new THREE.MeshStandardMaterial({ color: 0x5e625f, roughness: 0.8, metalness: 0.08 }),
  marble: new THREE.MeshStandardMaterial({ color: 0xd8d4ca, roughness: 0.5 }),
  marbleVein: new THREE.MeshStandardMaterial({ color: 0x928f89, roughness: 0.68, metalness: 0.02 }),
  brass: new THREE.MeshStandardMaterial({ color: 0x9f7b46, roughness: 0.32, metalness: 0.74 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0xd9e2dd, roughness: 0.13, metalness: 0, transmission: 0.62, transparent: true, opacity: 0.39, thickness: 0.35, side: THREE.DoubleSide }),
  bulb: new THREE.MeshStandardMaterial({ color: 0xe8d8a7, roughness: 0.35, emissive: 0x2b210e, emissiveIntensity: 0.18 }),
  bedUpholstery: new THREE.MeshStandardMaterial({ color: 0x626663, roughness: 0.92 }),
  bedUpholsteryLight: new THREE.MeshStandardMaterial({ color: 0x85857f, roughness: 0.95 }),
  bedInterior: new THREE.MeshStandardMaterial({ color: 0x242725, roughness: 0.9 }),
  mattress: new THREE.MeshStandardMaterial({ color: 0xd5d0c5, roughness: 0.98 }),
  mattressSide: new THREE.MeshStandardMaterial({ color: 0xb4afa5, roughness: 0.99 }),
  sheet: new THREE.MeshStandardMaterial({ color: 0xc4bcad, roughness: 0.99 }),
  duvet: new THREE.MeshStandardMaterial({ color: 0xe2ded4, roughness: 1 }),
  pillow: new THREE.MeshStandardMaterial({ color: 0xe9e4da, roughness: 0.97 }),
  beddingSeam: new THREE.MeshStandardMaterial({ color: 0xbcb4a7, roughness: 1 }),
  sill: new THREE.MeshStandardMaterial({ color: 0x6b706c, roughness: 0.86, metalness: 0.04 }),
  alexaBand: new THREE.MeshStandardMaterial({ color: 0x59615f, roughness: 0.42, metalness: 0.12, emissive: 0x07100e, emissiveIntensity: 0.06 }),
  pcPanel: new THREE.MeshStandardMaterial({ color: 0x101413, roughness: 0.52, metalness: 0.28 }),
  pcComponent: new THREE.MeshStandardMaterial({ color: 0x252a28, roughness: 0.62, metalness: 0.34 }),
  pcAccent: new THREE.MeshStandardMaterial({ color: 0x167d83, roughness: 0.38, metalness: 0.2, emissive: 0x063a3d, emissiveIntensity: 0.48 }),
  projectorShell: new THREE.MeshStandardMaterial({ color: 0xf4f1e8, roughness: 0.34, metalness: 0.02 }),
  projectorVent: new THREE.MeshStandardMaterial({ color: 0xc7cbc6, roughness: 0.62, metalness: 0.02 }),
  projectorVentVoid: new THREE.MeshStandardMaterial({ color: 0x303534, roughness: 0.78 }),
  projectorLensHousing: new THREE.MeshStandardMaterial({ color: 0x111514, roughness: 0.27, metalness: 0.22 }),
  projectorLensGlass: new THREE.MeshStandardMaterial({ color: 0x142b27, roughness: 0.1, metalness: 0.46, emissive: 0x06130f, emissiveIntensity: 0.45 }),
  projectorControl: new THREE.MeshStandardMaterial({ color: 0x313635, roughness: 0.48, metalness: 0.16 }),
  projectorIndicator: new THREE.MeshStandardMaterial({ color: 0x5da8ff, roughness: 0.24, emissive: 0x2877d5, emissiveIntensity: 0.9 }),
  chairUpholstery: new THREE.MeshStandardMaterial({ color: 0xf2efe6, roughness: 0.76, metalness: 0 }),
  chairSeam: new THREE.MeshStandardMaterial({ color: 0xd1cabd, roughness: 0.9, metalness: 0 }),
  chairUnderside: new THREE.MeshStandardMaterial({ color: 0x252827, roughness: 0.61, metalness: 0.16 }),
  keyboard: new THREE.MeshStandardMaterial({ color: 0x171a19, roughness: 0.54, metalness: 0.12 }),
  keyboardKey: new THREE.MeshStandardMaterial({ color: 0x303534, roughness: 0.68, metalness: 0.04 }),
  mouse: new THREE.MeshStandardMaterial({ color: 0x1c201f, roughness: 0.45, metalness: 0.1 }),
  mouseDetail: new THREE.MeshStandardMaterial({ color: 0x454b49, roughness: 0.5, metalness: 0.18 }),
})

function mesh(world, geometry, material, name) {
  const item = new THREE.Mesh(geometry, material)
  item.name = name
  item.castShadow = true
  item.receiveShadow = true
  world.add(item)
  return item
}

function box(world, w, d, h, x, y, z, material, name) {
  const item = mesh(world, new THREE.BoxGeometry(w, d, h), material, name)
  item.position.set(x, y, z)
  return item
}

function cylinderZ(world, top, bottom, h, x, y, z, material, name, segments = 16) {
  const item = mesh(world, new THREE.CylinderGeometry(top, bottom, h, segments), material, name)
  item.rotation.x = Math.PI / 2
  item.position.set(x, y, z)
  return item
}

function ellipsoid(world, w, d, h, x, y, z, material, name, segments = 20) {
  const geometry = new THREE.SphereGeometry(1, segments, Math.max(12, Math.floor(segments * 0.7)))
  geometry.scale(w / 2, d / 2, h / 2)
  const item = mesh(world, geometry, material, name)
  item.position.set(x, y, z)
  return item
}

function roundedRectGeometry(w, d, h, radius = 4) {
  const r = Math.min(radius, w / 2 - 0.1, d / 2 - 0.1)
  const shape = new THREE.Shape()
  shape.moveTo(-w / 2 + r, -d / 2)
  shape.lineTo(w / 2 - r, -d / 2)
  shape.quadraticCurveTo(w / 2, -d / 2, w / 2, -d / 2 + r)
  shape.lineTo(w / 2, d / 2 - r)
  shape.quadraticCurveTo(w / 2, d / 2, w / 2 - r, d / 2)
  shape.lineTo(-w / 2 + r, d / 2)
  shape.quadraticCurveTo(-w / 2, d / 2, -w / 2, d / 2 - r)
  shape.lineTo(-w / 2, -d / 2 + r)
  shape.quadraticCurveTo(-w / 2, -d / 2, -w / 2 + r, -d / 2)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: h,
    bevelEnabled: true,
    bevelSegments: 3,
    bevelSize: Math.min(2.2, h * 0.22),
    bevelThickness: Math.min(1.2, h * 0.15),
  })
  geometry.translate(0, 0, -h / 2)
  return geometry
}

function roundedBox(world, w, d, h, x, y, z, material, name, radius = 4) {
  const item = mesh(world, roundedRectGeometry(w, d, h, radius), material, name)
  item.position.set(x, y, z)
  return item
}

function rod(world, start, end, radius, material, name) {
  const delta = new THREE.Vector3().subVectors(end, start)
  const item = mesh(world, new THREE.CylinderGeometry(radius, radius, delta.length(), 10), material, name)
  item.position.copy(start).add(end).multiplyScalar(0.5)
  item.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize())
  return item
}

function addBrayaBed(world) {
  const f = bedroomPhysical.objects.bed.plan_bounds_gu
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2

  // Braya remains entirely inside its accepted footprint. Camera-readable
  // gray rails form a continuous closed storage-platform perimeter.
  box(world, f.w - 18, f.h - 18, 8, cx + 2, cy, 40, m.bedInterior, 'Braya recessed closed storage cavity')
  roundedBox(world, f.w - 12, 15, 42, cx + 1, f.y + 8.2, 27, m.bedUpholstery, 'Braya visible near upholstered side rail', 3.6)
  roundedBox(world, f.w - 12, 15, 42, cx + 1, f.maxY - 8.2, 27, m.bedUpholstery, 'Braya visible far upholstered side rail', 3.6)
  roundedBox(world, 17, f.h - 15, 44, f.maxX - 8.8, cy, 28, m.bedUpholstery, 'Braya prominent continuous upholstered foot rail', 3.6)
  box(world, 1.2, f.h - 31, 1.2, f.maxX - 17.1, cy, 49.15, m.bedUpholsteryLight, 'Braya visible foot-rail center seam')
  box(world, 11, f.h - 22, 1.15, f.maxX - 17.1, cy, 49.05, m.bedUpholsteryLight, 'Braya visible foot-rail upper welt')

  // The product's headboard is thick, lightly winged, and divided into broad
  // horizontal upholstery bands rather than tufting or a thin slab.
  roundedBox(world, 15.4, f.h - 6, 122, f.x + 8.7, cy, 97, m.bedUpholstery, 'Braya substantial upholstered headboard backing', 3.5)
  for (const z of [69, 98, 127]) {
    roundedBox(world, 6.4, f.h - 26, 25, f.x + 16.3, cy, z, m.bedUpholsteryLight, 'Braya readable broad horizontal upholstered headboard panel', 2.8)
  }
  for (const y of [f.y + 9.2, f.maxY - 9.2]) {
    roundedBox(world, 17, 17, 130, f.x + 8.5, y, 100, m.bedUpholstery, 'Braya readable upholstered headboard wing', 3.6)
  }

  // Keep mattress, sheet, and bedding as visibly separate nested layers.
  roundedBox(world, f.w - 42, f.h - 38, 20, cx + 1, cy, 58, m.mattressSide, 'Braya clearly inset mattress sidewall', 4.2)
  roundedBox(world, f.w - 47, f.h - 43, 4.2, cx + 1, cy, 69.8, m.mattress, 'Braya clearly inset mattress top', 3.8)
  const sheet = mesh(world, new THREE.PlaneGeometry(f.w - 52, f.h - 48), m.sheet, 'Braya near-flush fitted sheet treatment')
  sheet.position.set(cx + 1, cy, 72.05)
  const duvet = mesh(world, drapedDuvetGeometry(f.w * 0.57, f.h * 0.70), m.duvet, 'Braya coherent soft draped duvet')
  duvet.position.set(f.x + f.w * 0.61, cy - 2.8, 72.2)
  for (const [y, rotation, height] of [
    [f.y + f.h * 0.30, -0.105, 13.2],
    [f.y + f.h * 0.70, 0.078, 14.4],
  ]) {
    const pillow = mesh(world, softPillowGeometry(f.w * 0.215, f.h * 0.29, height), m.pillow, 'Braya plump crowned pillow')
    pillow.position.set(f.x + f.w * 0.29, y, 73.8)
    pillow.rotation.z = rotation
  }
}

// A rounded module mounted on the outward-facing (+x) projector fascia. The
// renderer keeps the physical return footprint untouched while making the
// front's recognizably rounded gray vent wells readable at preview distance.
function frontRoundedBox(world, w, h, depth, x, y, z, material, name, radius = 2) {
  const item = roundedBox(world, h, w, depth, x, y, z, material, name, radius)
  item.rotation.y = Math.PI / 2
  return item
}

function addBurgenerDesk(world, data) {
  const structure = resolveBurgenerDeskStructure(bedroomPhysical)
  const { main, return: returnModule, topZ, undersideZ } = structure
  const mainTop = main.top
  const returnTop = returnModule.top
  const mainX = main.center.x
  const mainY = main.center.y
  const returnX = returnModule.center.x
  const returnY = returnModule.center.y

  // Physical module sizes come exclusively from Physical World v1.
  // The main top is a plain slab: its cap reaches the physical outer bounds
  // and its straight wood sides retain thickness without a chamfer/rim.
  box(world, mainTop.w, mainTop.h, 4.4, mainX, mainY, topZ, m.top, 'Burgener weathered gray-brown main worktop')
  roundedBox(world, returnTop.w, returnTop.h, 4.4, returnX, returnY, topZ, m.top, 'Burgener weathered gray-brown return worktop', 2.4)
  // Flat, irregular surface marks provide weathered grain without modeling
  // ribs, planks, seams, or a new texture asset pipeline.
  const mainWoodEnds = [
    [mainTop.x + mainTop.w * 0.12, mainTop.w * 0.18],
    [mainTop.maxX - mainTop.w * 0.12, mainTop.w * 0.18],
  ]
  for (const [x, width] of mainWoodEnds) {
    for (const [offset, length, material] of [
      [-mainTop.h * 0.27, width * 0.78, m.grain], [-mainTop.h * 0.07, width * 0.55, m.grainLight],
      [mainTop.h * 0.18, width * 0.68, m.grain], [mainTop.h * 0.34, width * 0.42, m.grainLight],
    ]) surfaceMark(world, length, 0.42, x, mainY + offset, topZ + 2.205, material, 'Burgener restrained main-top wood grain')
  }
  for (const [offset, length, material] of [
    [-returnTop.w * 0.25, returnTop.h * 0.74, m.grain], [-returnTop.w * 0.05, returnTop.h * 0.52, m.grainLight],
    [returnTop.w * 0.16, returnTop.h * 0.82, m.grain], [returnTop.w * 0.32, returnTop.h * 0.43, m.grainLight],
  ]) surfaceMark(world, 0.4, length, returnX + offset, returnY, topZ + 2.205, material, 'Burgener restrained return-top wood grain')
  // The 19.68-inch black-section depth is product evidence. Its long-axis
  // length is a provisional material treatment, not an object size.
  roundedBox(world, main.blackSurface.w, main.blackSurface.h, 1.1, main.blackSurface.x + main.blackSurface.w / 2, main.blackSurface.y + main.blackSurface.h / 2, topZ + 2.75, m.black, 'Burgener bounded black central work surface', 1.5)

  for (const leg of main.steelLegs) {
    box(world, leg.w, leg.d, leg.h, leg.x, leg.y, leg.z, m.steel, 'Burgener rectangular steel leg')
  }
  for (const [name, apron] of [['Burgener black front apron', main.frontApron], ['Burgener black side apron', main.sideApron]]) {
    box(world, apron.w, apron.d, apron.h, apron.x, apron.y, apron.z, m.steel, name)
  }

  // Return storage is a full-length dark, panel-built carcass with a
  // room-facing upper cubby band and two lower file drawers.
  for (const panel of returnModule.carcassPanels) {
    box(world, panel.w, panel.d, panel.h, panel.x, panel.y, panel.z, m.cabinet, 'Burgener dark return cabinet carcass panel')
  }
  for (const divider of returnModule.cubbyDividers) {
    box(world, divider.w, divider.d, divider.h, divider.x, divider.y, divider.z, m.cabinet, 'Burgener dark cubby divider')
  }
  for (const cubby of returnModule.cubbies) {
    box(world, cubby.w, cubby.d, cubby.h, cubby.x, cubby.y, cubby.z, m.void, 'Burgener room-facing open cubby')
  }
  for (const drawer of returnModule.drawers) {
    box(world, drawer.w, drawer.d, drawer.h, drawer.x, drawer.y, drawer.z, m.face, 'Burgener lower light-wood file drawer face')
  }
  for (const pull of returnModule.drawerPulls) {
    box(world, pull.w, pull.d, pull.h, pull.x, pull.y, pull.z, m.black, 'Burgener black drawer pull')
  }
}

function surfaceMark(world, w, d, x, y, z, material, name, rotation = 0) {
  const item = mesh(world, new THREE.PlaneGeometry(w, d), material, name)
  item.position.set(x, y, z)
  item.rotation.z = rotation
  return item
}

function softPillowGeometry(w, d, h, segments = 12) {
  const positions = []
  const indices = []
  const stride = segments + 1
  const count = stride * stride
  const addPoint = (u, v, z) => positions.push(
    u * w * 0.5 * (1 - 0.17 * v * v),
    v * d * 0.5 * (1 - 0.19 * u * u),
    z,
  )
  for (const top of [true, false]) {
    for (let row = 0; row <= segments; row += 1) {
      const v = -1 + row * 2 / segments
      for (let column = 0; column <= segments; column += 1) {
        const u = -1 + column * 2 / segments
        const crown = Math.pow(Math.max(0, (1 - u * u) * (1 - v * v)), 0.38)
        addPoint(u, v, top ? h * (0.06 + 0.94 * crown) : -h * (0.13 + 0.10 * crown))
      }
    }
  }
  for (let row = 0; row < segments; row += 1) {
    for (let column = 0; column < segments; column += 1) {
      const a = row * stride + column
      const b = a + 1
      const c = a + stride
      const d = c + 1
      indices.push(a, b, d, a, d, c, count + a, count + d, count + b, count + a, count + c, count + d)
    }
  }
  for (let index = 0; index < segments; index += 1) {
    const first = index * stride
    const next = (index + 1) * stride
    const last = first + segments
    const nextLast = next + segments
    indices.push(first, next, count + next, first, count + next, count + first)
    indices.push(last, count + last, nextLast, last, count + last, count + nextLast)
    indices.push(index, count + index, index + 1, index + 1, count + index, count + index + 1)
    const far = segments * stride + index
    indices.push(far, far + 1, count + far + 1, far, count + far + 1, count + far)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function drapedDuvetGeometry(w, d, segments = 16) {
  const positions = []
  const indices = []
  const stride = segments + 1
  const count = stride * stride
  const profile = (u, v) => {
    const crown = Math.pow(Math.max(0, (1 - u * u) * (1 - v * v)), 0.46)
    const broadFold = 0.72 * Math.sin((u + 0.18) * Math.PI * 1.45) * (1 - v * v)
    const crossFold = 0.44 * Math.sin((v - 0.13) * Math.PI * 1.05) * (1 - u * u)
    const footFall = 1.95 * Math.max(0, u) ** 2.5
    return 3.35 + 9.1 * crown + broadFold + crossFold - footFall
  }
  for (const top of [true, false]) {
    for (let row = 0; row <= segments; row += 1) {
      const v = -1 + row * 2 / segments
      for (let column = 0; column <= segments; column += 1) {
        const u = -1 + column * 2 / segments
        const crown = Math.max(0, (1 - u * u) * (1 - v * v))
        const sideInset = 1 - 0.075 * v * v * (0.65 + 0.35 * u)
        const footInset = 1 - 0.045 * Math.max(0, u) ** 2
        const outlineWobble = 0.014 * Math.sin((u + 0.22) * Math.PI * 1.4) * (1 - v * v)
        const baseX = u * w / 2 * (sideInset + outlineWobble)
        const baseY = v * d / 2 * footInset
        const edge = 1 - crown
        const drapeReach = edge * (0.035 + 0.060 * Math.max(0, u))
        const lowerDrop = 1.7 + 6.1 * edge + 2.05 * Math.max(0, u) ** 2
        positions.push(
          top ? baseX : baseX * (1 + drapeReach),
          top ? baseY : baseY * (1 + edge * (0.055 + 0.035 * Math.max(0, u))),
          profile(u, v) - (top ? 0 : lowerDrop),
        )
      }
    }
  }
  for (let row = 0; row < segments; row += 1) {
    for (let column = 0; column < segments; column += 1) {
      const a = row * stride + column
      const b = a + 1
      const c = a + stride
      const d = c + 1
      indices.push(a, b, d, a, d, c, count + a, count + d, count + b, count + a, count + c, count + d)
    }
  }
  for (let index = 0; index < segments; index += 1) {
    const first = index * stride
    const next = (index + 1) * stride
    const last = first + segments
    const nextLast = next + segments
    indices.push(first, next, count + next, first, count + next, count + first)
    indices.push(last, count + last, nextLast, last, count + last, count + nextLast)
    indices.push(index, count + index, index + 1, index + 1, count + index, count + index + 1)
    const far = segments * stride + index
    indices.push(far, far + 1, count + far + 1, far, count + far + 1, count + far)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function addHomeZeerChair(world, data) {
  const f = workstationAccessories.chair.bounds
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  // One continuous cushion gives the chair its ordinary upholstered-office
  // silhouette. It is deliberately not assembled from separate padded cells.
  const seatY = cy + 8
  const backY = f.y + 13.4
  const backFrontY = backY + 3.56
  roundedBox(world, f.w * 0.72, f.h * 0.49, 10.4, cx, seatY, 58.3, m.chairUpholstery, 'HomeZeer single continuous rounded upholstered seat cushion', 4.2)
  roundedBox(world, f.w * 0.67, 7.1, 63, cx, backY, 95, m.chairUpholstery, 'HomeZeer single continuous tall rounded upholstered backrest', 5.4)

  // The reference's 2-by-3 face is a lightly pinched upholstery treatment in
  // one backrest. Low-contrast, near-flush seam strips provide that read at
  // normal preview distance without turning the back into floating cushions.
  box(world, 0.52, 0.12, 53.5, cx, backFrontY + 0.07, 95, m.chairSeam, 'HomeZeer shallow central vertical backrest seam')
  for (const z of [84.7, 105.1]) {
    box(world, f.w * 0.56, 0.12, 0.48, cx, backFrontY + 0.07, z, m.chairSeam, 'HomeZeer shallow horizontal backrest tuft seam')
  }

  // Narrow white pads sit on polished bent side loops; their low profile is
  // visible in both the front and side product views.
  for (const sign of [-1, 1]) {
    const x = cx + sign * f.w * 0.38
    rod(world, new THREE.Vector3(x, seatY + 12, 54), new THREE.Vector3(x, backY + 1.8, 54), 1.16, m.chrome, 'HomeZeer polished lower arm loop rail')
    rod(world, new THREE.Vector3(x, backY + 1.8, 54), new THREE.Vector3(x, backY + 1.8, 80.5), 1.16, m.chrome, 'HomeZeer polished rear arm loop upright')
    rod(world, new THREE.Vector3(x, backY + 1.8, 80.5), new THREE.Vector3(x, seatY - 3.2, 85.2), 1.16, m.chrome, 'HomeZeer polished upper arm loop rail')
    roundedBox(world, 5.7, 17.4, 2.85, x, seatY - 2.6, 86.4, m.chairUpholstery, 'HomeZeer narrow rounded white upholstered arm pad', 1.2)
  }
  roundedBox(world, f.w * 0.47, f.h * 0.22, 2.8, cx, cy + 9, 48.6, m.chairUnderside, 'HomeZeer dark under-seat tilt plate', 1.2)
  rod(world, new THREE.Vector3(cx - f.w * 0.23, cy + 11, 49), new THREE.Vector3(cx - f.w * 0.29, cy + 17, 45.8), 0.82, m.chairUnderside, 'HomeZeer black under-seat adjustment lever')
  ellipsoid(world, 2.1, 2.1, 3.1, cx - f.w * 0.29, cy + 17, 45.8, m.chairUnderside, 'HomeZeer black adjustment lever handle')
  cylinderZ(world, 3.4, 3.4, 39, cx, cy + 9, 30, m.chrome, 'HomeZeer polished central gas lift')
  cylinderZ(world, 6.6, 7.6, 4, cx, cy + 9, 10.5, m.chrome, 'HomeZeer polished five-star hub')
  const center = new THREE.Vector3(cx, cy + 9, 10)
  for (let index = 0; index < 5; index += 1) {
    const angle = Math.PI * 2 * index / 5 + Math.PI / 2
    const tip = new THREE.Vector3(cx + Math.cos(angle) * f.w * 0.37, cy + 9 + Math.sin(angle) * f.h * 0.31, 6)
    rod(world, center, tip, 1.48, m.chrome, 'HomeZeer polished five-star base spoke')
    cylinderZ(world, 1.25, 1.5, 3.2, tip.x, tip.y, 5.1, m.chairUnderside, 'HomeZeer dark twin-wheel caster fork', 12)
    const tangent = new THREE.Vector3(-Math.sin(angle), Math.cos(angle), 0)
    for (const sign of [-1, 1]) {
      ellipsoid(world, 3.9, 3.2, 5.2, tip.x + tangent.x * sign * 1.55, tip.y + tangent.y * sign * 1.55, 3.25, m.caster, 'HomeZeer black twin-wheel caster')
    }
  }
}

function addOdysseyMonitor(world) {
  const f = workstationAccessories.monitor.bounds
  const cx = f.x + f.w / 2
  const panelY = f.y + f.h * 0.47
  const top = 104.4
  const panelH = f.w * 9 / 16
  // One restrained 27-inch 16:9 Odyssey assembly: a thin black screen shell,
  // low angular foot, and central neck distinguish it from a generic panel.
  ellipsoid(world, f.w * 0.37, 10.4, 1.55, cx, f.y + f.h * 0.28, top + 0.9, m.monitor, 'Samsung Odyssey G5 low oval stand foot')
  box(world, f.w * 0.19, 5.2, 1.05, cx, f.y + f.h * 0.30, top + 1.35, m.displayEdge, 'Samsung Odyssey G5 stand-foot center plate')
  roundedBox(world, 4.7, 3.4, 18.8, cx, f.y + f.h * 0.48, top + 10.2, m.monitor, 'Samsung Odyssey G5 tapered central neck', 1.1)
  box(world, f.w, 3.05, panelH, cx, panelY, top + 17 + panelH / 2, m.monitor, 'Samsung Odyssey G5 dark rear housing')
  box(world, f.w * 0.967, 0.38, panelH * 0.956, cx, panelY - 1.68, top + 17 + panelH / 2, m.displayEdge, 'Samsung Odyssey G5 thin black display bezel')
  box(world, f.w * 0.942, 0.22, panelH * 0.922, cx, panelY - 1.94, top + 17 + panelH / 2, m.display, 'Samsung Odyssey G5 subtle dark display panel')
  box(world, 11, 0.5, 1.25, cx, panelY + 1.72, top + 17 + panelH * 0.12, m.displayEdge, 'Samsung Odyssey G5 rear lower control housing')
}

function addBlueYeti(world) {
  const f = workstationAccessories.microphone.bounds
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  // Accepted raw anchor intentionally becomes the user's right with reflection.
  cylinderZ(world, 4.65, 5.15, 1.55, cx, cy, z + 0.78, m.mic, 'Blue Yeti weighted circular desktop base')
  cylinderZ(world, 3.5, 3.62, 12.8, cx, cy, z + 10.1, m.grille, 'Blue Yeti perforated cylindrical grille')
  cylinderZ(world, 3.15, 3.48, 5.4, cx, cy, z + 3.45, m.mic, 'Blue Yeti matte black lower body')
  ellipsoid(world, 6.95, 6.95, 4.6, cx, cy, z + 16.5, m.grille, 'Blue Yeti rounded grille cap')
  for (const offset of [-4.2, 4.2]) {
    rod(world, new THREE.Vector3(cx + offset, cy, z + 3), new THREE.Vector3(cx + offset, cy, z + 14.2), 0.78, m.mic, 'Blue Yeti compact side yoke')
    cylinderZ(world, 1.22, 1.22, 1.55, cx + offset, cy - 3.25, z + 10.1, m.micControl, 'Blue Yeti knurled yoke knob')
  }
  for (const band of [z + 9.2, z + 12.4]) box(world, 6.25, 0.38, 0.42, cx, cy - 3.48, band, m.mic, 'Blue Yeti restrained grille band')
  cylinderZ(world, 0.85, 0.85, 0.28, cx, cy - 3.53, z + 6.2, m.micControl, 'Blue Yeti front gain control')
  box(world, 1.4, 0.2, 0.7, cx, cy - 3.55, z + 8, m.micControl, 'Blue Yeti small front status window')
}

function addKeyboardAndMouse(world) {
  const keyboard = workstationAccessories.keyboard.bounds
  const keyboardCenterX = keyboard.x + keyboard.w / 2
  const keyboardCenterY = keyboard.y + keyboard.h / 2
  const deskTopZ = 105.4
  const keyboardHeight = 2.65

  // The photo establishes a compact dark board centered beneath the monitor.
  // Keep the key grid intentionally low contrast so it reads at the normal
  // camera without becoming a branded or exaggerated mechanical keyboard.
  roundedBox(world, keyboard.w, keyboard.h, keyboardHeight, keyboardCenterX, keyboardCenterY, deskTopZ + keyboardHeight / 2, m.keyboard, 'Bedroom low-profile dark keyboard body', 2.2)
  const rows = 5
  const columns = 12
  const keyGap = 0.9
  const keyW = (keyboard.w - 7 - keyGap * (columns - 1)) / columns
  const keyD = (keyboard.h - 5.4 - keyGap * (rows - 1)) / rows
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const x = keyboard.x + 3.5 + keyW / 2 + column * (keyW + keyGap)
      const y = keyboard.y + 2.7 + keyD / 2 + row * (keyD + keyGap)
      const width = row === rows - 1 && column >= 3 && column <= 7 ? keyW * 1.28 : keyW
      roundedBox(world, width, keyD, 0.38, x, y, deskTopZ + keyboardHeight + 0.19, m.keyboardKey, 'Bedroom keyboard subtle keycap relief', 0.35)
    }
  }

  const mouse = workstationAccessories.mouse.bounds
  const mouseCenterX = mouse.x + mouse.w / 2
  const mouseCenterY = mouse.y + mouse.h / 2
  ellipsoid(world, mouse.w, mouse.h, 4.8, mouseCenterX, mouseCenterY, deskTopZ + 2.4, m.mouse, 'Bedroom compact dark ergonomic mouse', 18)
  box(world, 0.34, mouse.h * 0.42, 0.16, mouseCenterX, mouse.y + mouse.h * 0.31, deskTopZ + 4.72, m.mouseDetail, 'Bedroom mouse restrained left-right button separation')
  cylinderZ(world, 0.58, 0.58, 0.28, mouseCenterX, mouse.y + mouse.h * 0.50, deskTopZ + 4.78, m.mouseDetail, 'Bedroom mouse subtle scroll wheel')
}

function addDrumLamp(world) {
  const f = workstationAccessories.leftLamp.bounds
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  // Opaque open shell plus perimeter rims: no transparent, spoke, or radial
  // cap mesh can be exposed from this conventional fabric table lamp.
  cylinderZ(world, 8.9, 7.05, 10.8, cx, cy, z + 5.4, m.stone, 'L2 broad faceted graphite lamp base', 6)
  cylinderZ(world, 6.5, 6.5, 1.1, cx, cy, z + 0.55, m.trim, 'L2 dark hexagonal base plinth', 6)
  cylinderZ(world, 2.25, 2.25, 7.8, cx, cy, z + 14.25, m.trim, 'L2 short centered lamp neck', 12)
  const shade = mesh(world, new THREE.CylinderGeometry(15.15, 13.35, 32.2, 32, 1, true), m.lampLinen, 'L2 opaque warm fabric shade shell')
  shade.rotation.x = Math.PI / 2
  shade.position.set(cx, cy, z + 34.35)
  mesh(world, new THREE.TorusGeometry(13.35, 0.44, 6, 32), m.trim, 'L2 lower fabric shade perimeter rim').position.set(cx, cy, z + 18.25)
  mesh(world, new THREE.TorusGeometry(15.15, 0.44, 6, 32), m.trim, 'L2 upper fabric shade perimeter rim').position.set(cx, cy, z + 50.45)
}

function cylinderX(world, left, right, radius, y, z, material, name, segments = 16) {
  const item = mesh(world, new THREE.CylinderGeometry(radius, radius, right - left, segments), material, name)
  item.rotation.z = -Math.PI / 2
  item.position.set((left + right) / 2, y, z)
  return item
}

function addEpsonProjector(world) {
  const f = bedroomPhysical.objects.projector.plan_bounds_gu
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const supportTopZ = bedroomPhysical.objects.return.dimensions_gu.high + 2.2
  const z = supportTopZ + 1.5
  const bodyW = f.w
  const bodyD = f.h
  const bodyH = 8.3
  const frontX = cx + bodyW / 2
  const topZ = z + bodyH

  // The supplied front reference has separate black adjustable feet under a
  // broad glossy shell, not one continuous dark plinth.
  for (const y of [cy - bodyD * 0.36, cy + bodyD * 0.36]) {
    cylinderZ(world, 1.22, 1.42, 1.35, frontX - 1.35, y, z - 0.68, m.projectorLensHousing, 'Epson H421A black knurled front adjustment foot', 16)
    cylinderZ(world, 1.55, 1.55, 0.24, frontX - 1.35, y, z - 1.42, m.projectorControl, 'Epson H421A front foot contact pad', 16)
  }
  for (const y of [cy - bodyD * 0.34, cy + bodyD * 0.34]) {
    cylinderZ(world, 1.08, 1.08, 0.92, cx - bodyW * 0.35, y, z - 0.46, m.projectorShell, 'Epson H421A rear shell support foot', 16)
  }

  roundedBox(world, bodyW, bodyD, bodyH, cx, cy, z + bodyH / 2, m.projectorShell, 'Epson H421A wide rounded glossy white shell above return', 2.6)

  // The real fascia is a three-part composition: two deep gray louver bays
  // framing a much larger centered lens, rather than a generic single grille.
  const ventW = bodyD * 0.237
  const ventH = bodyH * 0.66
  const ventCenters = [cy - bodyD * 0.335, cy + bodyD * 0.335]
  for (const y of ventCenters) {
    frontRoundedBox(world, ventW, ventH, 0.55, frontX + 0.19, y, z + bodyH * 0.51, m.projectorVentVoid, 'Epson H421A deep rounded front vent cavity', 1.75)
    frontRoundedBox(world, ventW * 0.91, ventH * 0.91, 0.19, frontX + 0.51, y, z + bodyH * 0.51, m.projectorVent, 'Epson H421A light gray rounded vent surround', 1.4)
    for (const offset of [-0.34, -0.17, 0, 0.17, 0.34]) {
      box(world, 0.24, 0.42, ventH * 0.77, frontX + 0.67, y + ventW * offset, z + bodyH * 0.51, m.projectorVent, 'Epson H421A tall vertical front vent louver')
    }
  }

  const lensZ = z + bodyH * 0.51
  cylinderX(world, frontX - 0.18, frontX + 0.92, 3.92, cy, lensZ, m.projectorLensHousing, 'Epson H421A large centered black lens outer barrel', 32)
  cylinderX(world, frontX + 0.84, frontX + 1.13, 3.34, cy, lensZ, m.projectorControl, 'Epson H421A stepped lens inner barrel', 32)
  cylinderX(world, frontX + 1.10, frontX + 1.22, 2.68, cy, lensZ, m.projectorLensGlass, 'Epson H421A centered green-black lens glass', 32)
  cylinderX(world, frontX + 1.21, frontX + 1.25, 1.08, cy, lensZ, m.projectorIndicator, 'Epson H421A small illuminated lens core', 24)

  // Its deep top adjustment bay sits forward of the wordmark. It is bounded
  // visual relief only: no plan, anchor, support, or desk dimensions change.
  const recessX = cx + bodyW * 0.13
  roundedBox(world, bodyW * 0.38, bodyD * 0.25, 0.25, recessX, cy, topZ + 0.12, m.projectorVentVoid, 'Epson H421A recessed top lens-shift adjustment well', 1.05)
  roundedBox(world, bodyW * 0.25, bodyD * 0.15, 0.3, recessX + bodyW * 0.015, cy, topZ + 0.25, m.projectorControl, 'Epson H421A black lens-shift adjustment assembly', 0.65)
  box(world, bodyW * 0.19, 0.58, 0.17, recessX + bodyW * 0.015, cy - bodyD * 0.06, topZ + 0.44, m.projectorVent, 'Epson H421A lens-shift slider highlight')

  // Compact control island from the top reference: power/source below a
  // circular navigation ring, with distinct Menu and Esc buttons nearby.
  const controlsX = cx - bodyW * 0.18
  const controlsY = cy - bodyD * 0.12
  cylinderZ(world, 1.66, 1.66, 0.2, controlsX, controlsY, topZ + 0.13, m.projectorControl, 'Epson H421A circular top navigation ring', 24)
  cylinderZ(world, 0.82, 0.82, 0.26, controlsX, controlsY, topZ + 0.29, m.projectorShell, 'Epson H421A central enter control', 20)
  cylinderZ(world, 1.03, 1.03, 0.26, controlsX - bodyW * 0.12, controlsY, topZ + 0.27, m.projectorControl, 'Epson H421A round source control', 20)
  cylinderZ(world, 1.03, 1.03, 0.26, controlsX + bodyW * 0.12, controlsY, topZ + 0.27, m.projectorShell, 'Epson H421A round blue power control surround', 20)
  cylinderZ(world, 0.48, 0.48, 0.31, controlsX + bodyW * 0.12, controlsY, topZ + 0.43, m.projectorIndicator, 'Epson H421A blue power button center', 16)
  for (const [x, y, name] of [
    [controlsX - bodyW * 0.10, controlsY - bodyD * 0.16, 'Epson H421A top Menu button'],
    [controlsX + bodyW * 0.02, controlsY - bodyD * 0.16, 'Epson H421A top Esc button'],
  ]) roundedBox(world, 1.55, 0.92, 0.22, x, y, topZ + 0.17, m.projectorControl, name, 0.36)
  for (const x of [controlsX - bodyW * 0.19, controlsX - bodyW * 0.24]) {
    cylinderZ(world, 0.23, 0.23, 0.18, x, controlsY + bodyD * 0.15, topZ + 0.18, m.projectorControl, 'Epson H421A top status indicator aperture', 12)
  }
}

function addDeskAccessories(world) {
  const headphones = workstationAccessories.headphones.bounds
  {
    const group = new THREE.Group()
    group.name = 'Desk headphones fixed world-space assembly'
    group.position.set(headphones.x + headphones.w / 2, headphones.y + headphones.h / 2, 105.5)
    world.add(group)
    const band = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-5.3, -1.4, 1.15), new THREE.Vector3(-4.3, 1.9, 1.15),
      new THREE.Vector3(0, 3.35, 1.15), new THREE.Vector3(4.3, 1.9, 1.15), new THREE.Vector3(5.3, -1.4, 1.15),
    ])
    mesh(group, new THREE.TubeGeometry(band, 16, 1.05, 10, false), m.mic, 'Desk headphones flat padded headband arc')
    ellipsoid(group, 5.4, 4.75, 2.6, -4.8, -1.3, 1.3, m.grille, 'Desk headphones flat left ear cup')
    ellipsoid(group, 5.4, 4.75, 2.6, 4.8, -1.3, 1.3, m.grille, 'Desk headphones flat right ear cup')
  }

  const alexa = workstationAccessories.alexa.bounds
  {
    const group = new THREE.Group()
    group.name = 'Desk Alexa fixed world-space assembly'
    group.position.set(alexa.x + alexa.w / 2, alexa.y + alexa.h / 2, 105.5)
    world.add(group)
    cylinderZ(group, 4.7, 4.95, 3.8, 0, 0, 1.9, m.cabinet, 'Desk Alexa low fabric-style puck body')
    cylinderZ(group, 4.72, 4.72, 0.34, 0, 0, 3.95, m.alexaBand, 'Desk Alexa subdued top light ring')
    cylinderZ(group, 3.95, 3.95, 0.24, 0, 0, 4.24, m.black, 'Desk Alexa matte top disk')
  }
}

function addMarblePendantLamp(world) {
  const rightLamp = workstationAccessories.rightLamp
  const f = rightLamp.bounds
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  const lamp = new THREE.Group()
  lamp.name = 'L5 main-desk marble pendant lamp assembly'
  lamp.position.set(cx, cy, z)
  lamp.rotation.z = rightLamp.yaw_radians
  world.add(lamp)
  box(lamp, 22, 13, 3.8, 0, 0, 1.9, m.marble, 'L5 white marble rectangular base')
  box(lamp, 20.6, 11.6, 0.35, 0, 0, 3.95, m.marble, 'L5 raised marble base surface')
  box(lamp, 8.5, 0.18, 0.24, -2.2, -5.82, 4.16, m.marbleVein, 'L5 restrained marble front vein')
  box(lamp, 5.8, 0.18, 0.18, 5.1, -5.82, 4.16, m.marbleVein, 'L5 restrained marble front accent vein')
  cylinderZ(lamp, 1.24, 1.24, 47, rightLamp.stem_local_x_gu, 0, 27.7, m.brass, 'L5 slender brass stem', 12)
  cylinderZ(lamp, 2.05, 2.05, 1.2, rightLamp.stem_local_x_gu, 0, 4.6, m.brass, 'L5 brass stem foot', 12)
  const hook = new THREE.CatmullRomCurve3([
    new THREE.Vector3(rightLamp.stem_local_x_gu, 0, 50), new THREE.Vector3(rightLamp.stem_local_x_gu, 0, 62),
    new THREE.Vector3(-5, 0, 65), new THREE.Vector3(rightLamp.shade_local_x_gu, 0, 57),
  ])
  mesh(lamp, new THREE.TubeGeometry(hook, 20, 1.24, 10, false), m.brass, 'L5 inward-curving brass top hook')
  cylinderZ(lamp, 8.35, 8.35, 28.5, rightLamp.shade_local_x_gu, 0, 42, m.glass, 'L5 clear seeded-glass hanging shade', 20)
  cylinderZ(lamp, 3.2, 3.7, 9.2, rightLamp.shade_local_x_gu, 0, 42, m.bulb, 'L5 small visible hanging bulb', 14)
  cylinderZ(lamp, 4.85, 4.85, 3.15, rightLamp.shade_local_x_gu, 0, 58, m.brass, 'L5 brushed brass glass cap', 16)
  cylinderZ(lamp, 5.05, 5.05, 0.5, rightLamp.shade_local_x_gu, 0, 56.2, m.brass, 'L5 glass-cap lower collar', 16)
}

function addUnderMainPc(world) {
  const pc = workstationAccessories.pc
  const f = pc.bounds
  const footHeight = 3.2
  const bodyHeight = pc.height_gu - footHeight
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  // The visual assembly remains wholly inside the resolved PC envelope.
  roundedBox(world, f.w, f.h, bodyHeight, cx, cy, footHeight + bodyHeight / 2, m.cabinet, 'PC tower under main return-side working span', 2)
  for (const x of [f.x + 3.4, f.maxX - 3.4]) {
    for (const y of [f.y + 3.6, f.maxY - 3.6]) box(world, 3.4, 3.4, footHeight, x, y, footHeight / 2, m.pcPanel, 'PC tower inset base foot')
  }
  box(world, f.w * 0.58, 0.5, bodyHeight * 0.66, cx, f.y + 0.3, footHeight + bodyHeight * 0.52, m.void, 'PC tower recessed front intake')
  box(world, f.w * 0.43, 0.3, bodyHeight * 0.43, cx, f.y + 0.57, footHeight + bodyHeight * 0.55, m.pcPanel, 'PC tower differentiated front face')
  box(world, 0.55, f.h * 0.8, bodyHeight * 0.78, f.maxX - 0.28, cy, footHeight + bodyHeight * 0.52, m.glass, 'PC tower room-visible glass side panel')
  box(world, 0.55, f.h * 0.6, bodyHeight * 0.54, f.maxX - 0.72, cy, footHeight + bodyHeight * 0.5, m.pcComponent, 'PC tower internal dark component mass')
  for (const [y, z] of [[cy - f.h * 0.18, 25], [cy + f.h * 0.12, 42]]) {
    box(world, 0.3, f.h * 0.22, 2.2, f.maxX - 0.97, y, z, m.pcAccent, 'PC tower restrained cyan internal accent')
  }
}

export function addBedroomDesignPassV1(world, data) {
  // Keep the recovered workstation independent of future bedding experiments.
  addBedroomWindowSill(world)
  addBurgenerDesk(world, data)
  addHomeZeerChair(world, data)
  addOdysseyMonitor(world)
  addBlueYeti(world)
  addKeyboardAndMouse(world)
  addDrumLamp(world)
  addMarblePendantLamp(world)
  addUnderMainPc(world)
  addEpsonProjector(world)
  addDeskAccessories(world)
  addBrayaBed(world)
}

function addBedroomWindowSill(world) {
  const sill = bedroomPhysical.architecture.windowSill
  const f = sill.plan_bounds_gu
  const preview = sill.preview_placement
  // This is an additive, local architectural projection hosted by the bedroom
  // window—not the Burgener return and not a wall-length band. Its dimensions
  // remain explicitly provisional until the physical sill is measured.
  box(world, f.w, f.h, preview.thickness_gu, f.x + f.w / 2, f.y + f.h / 2, preview.top_z_gu - preview.thickness_gu / 2, m.sill, 'Bedroom local window sill / projecting ledge')
}
