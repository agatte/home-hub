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
  bedUpholstery: new THREE.MeshStandardMaterial({ color: 0x77736d, roughness: 0.94 }),
  bedUpholsteryLight: new THREE.MeshStandardMaterial({ color: 0x89847d, roughness: 0.96 }),
  bedInterior: new THREE.MeshStandardMaterial({ color: 0x242725, roughness: 0.9 }),
  mattress: new THREE.MeshStandardMaterial({ color: 0xe5e1d8, roughness: 0.98 }),
  sheet: new THREE.MeshStandardMaterial({ color: 0xd4cab9, roughness: 0.99 }),
  duvet: new THREE.MeshStandardMaterial({ color: 0xf0ede5, roughness: 1 }),
  beddingSeam: new THREE.MeshStandardMaterial({ color: 0xcfc8bc, roughness: 1 }),
  sill: new THREE.MeshStandardMaterial({ color: 0x6b706c, roughness: 0.86, metalness: 0.04 }),
  alexaBand: new THREE.MeshStandardMaterial({ color: 0x59615f, roughness: 0.42, metalness: 0.12, emissive: 0x07100e, emissiveIntensity: 0.06 }),
  pcPanel: new THREE.MeshStandardMaterial({ color: 0x101413, roughness: 0.52, metalness: 0.28 }),
  pcComponent: new THREE.MeshStandardMaterial({ color: 0x252a28, roughness: 0.62, metalness: 0.34 }),
  pcAccent: new THREE.MeshStandardMaterial({ color: 0x167d83, roughness: 0.38, metalness: 0.2, emissive: 0x063a3d, emissiveIntensity: 0.48 }),
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

  // Braya's closed storage base is low and upholstered, with distinctly
  // substantial rails and raised headboard wings rather than a generic slab.
  box(world, f.w - 18, f.h - 18, 7, cx + 3, cy, 43, m.bedInterior, 'Braya recessed storage deck')
  roundedBox(world, f.w - 20, 11, 38, cx + 3, f.y + 7, 25, m.bedUpholstery, 'Braya near upholstered side rail', 3)
  roundedBox(world, f.w - 20, 11, 38, cx + 3, f.y + f.h - 7, 25, m.bedUpholstery, 'Braya far upholstered side rail', 3)
  roundedBox(world, 13, f.h - 22, 41, f.x + f.w - 7, cy, 27, m.bedUpholstery, 'Braya upholstered foot rail', 3)
  box(world, 3.2, f.h - 42, 1.2, f.x + f.w - 12.5, cy, 47.4, m.bedUpholsteryLight, 'Braya foot-rail top seam')

  box(world, 11, f.h - 16, 108, f.x + 6.5, cy, 94, m.bedUpholstery, 'Braya upholstered headboard backing')
  for (const z of [77, 113]) {
    roundedBox(world, 6.2, f.h - 38, 28, f.x + 11.2, cy, z, m.bedUpholsteryLight, 'Braya broad horizontal padded headboard band', 3.4)
  }
  for (const y of [f.y + 10, f.y + f.h - 10]) {
    roundedBox(world, 16, 15, 122, f.x + 7.5, y, 97, m.bedUpholstery, 'Braya raised upholstered headboard wing', 3.5)
  }

  // Keep recovery bedding intentionally simple until the workstation checkpoint
  // is visually accepted.
  roundedBox(world, f.w - 34, f.h - 32, 24, cx + 4, cy, 62, m.mattress, 'Braya mattress', 5)
  roundedBox(world, f.w - 43, f.h - 42, 2.6, cx + 4, cy, 75.2, m.sheet, 'Braya fitted-sheet reveal', 4)
  roundedBox(world, f.w * 0.59, f.h * 0.80, 10, f.x + f.w * 0.61, cy, 82.5, m.duvet, 'Braya tidy puffy duvet', 8)
  for (const y of [f.y + f.h * 0.29, f.y + f.h * 0.70]) {
    roundedBox(world, f.w * 0.23, f.h * 0.26, 14, f.x + f.w * 0.29, y, 84, m.duvet, 'Braya shaped white pillow', 8)
  }
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

function addHomeZeerChair(world, data) {
  const f = workstationAccessories.chair.bounds
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  ellipsoid(world, f.w * 0.66, f.h * 0.5, 14, cx, cy + 8, 56, m.white, 'HomeZeer padded seat')
  box(world, f.w * 0.63, 7.5, 58, cx, f.y + 9.5, 94, m.white, 'HomeZeer stitched mid-back')
  for (const x of [-f.w * 0.16, f.w * 0.16]) box(world, 1, 8, 54, cx + x, f.y + 5.4, 94, m.stitch, 'HomeZeer vertical seam')
  box(world, f.w * 0.55, 1.1, 1.1, cx, f.y + 5.8, 96, m.stitch, 'HomeZeer horizontal seam')
  for (const sign of [-1, 1]) {
    const x = cx + sign * f.w * 0.38
    rod(world, new THREE.Vector3(x, cy + 8, 53), new THREE.Vector3(x, cy + 5, 80), 1.55, m.chrome, 'HomeZeer chrome arm upright')
    rod(world, new THREE.Vector3(x, cy + 5, 80), new THREE.Vector3(x, f.y + 10, 88), 1.55, m.chrome, 'HomeZeer chrome arm return')
    ellipsoid(world, 6.5, 17, 3.8, x, cy + 1.5, 88, m.white, 'HomeZeer white arm pad')
  }
  cylinderZ(world, 3.4, 3.4, 39, cx, cy + 9, 30, m.chrome, 'HomeZeer chrome gas lift')
  cylinderZ(world, 6.6, 7.6, 4, cx, cy + 9, 10.5, m.chrome, 'HomeZeer five-star hub')
  const center = new THREE.Vector3(cx, cy + 9, 10)
  for (let index = 0; index < 5; index += 1) {
    const angle = Math.PI * 2 * index / 5 + Math.PI / 2
    const tip = new THREE.Vector3(cx + Math.cos(angle) * f.w * 0.37, cy + 9 + Math.sin(angle) * f.h * 0.31, 6)
    rod(world, center, tip, 1.65, m.chrome, 'HomeZeer chrome five-star spoke')
    ellipsoid(world, 7, 6, 8, tip.x, tip.y, 4.5, m.caster, 'HomeZeer black caster')
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
  box(world, bodyW, bodyD, 1.5, cx, cy, z - 0.75, m.black, 'Epson H421A supported feet')
  roundedBox(world, bodyW, bodyD, bodyH, cx, cy, z + bodyH / 2, m.white, 'Epson H421A projector body above return', 2.6)
  roundedBox(world, bodyW * 0.62, bodyD * 0.72, 0.7, cx - bodyW * 0.10, cy, z + bodyH + 0.35, m.stone, 'Epson H421A gray top inset', 1.4)
  cylinderX(world, cx + bodyW / 2 - 0.3, cx + bodyW / 2 + 2.6, 3.25, cy - bodyD * 0.23, z + bodyH * 0.56, m.void, 'Epson H421A offset horizontal lens', 24)
  for (const yOffset of [-0.27, -0.08, 0.11, 0.30]) {
    box(world, 0.8, bodyD * 0.12, 2.8, cx + bodyW / 2 + 0.14, cy + bodyD * yOffset, z + bodyH * 0.53, m.black, 'Epson H421A front grille')
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
