import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { parseRational } from '../apartment-whitebox/adapter.js'

// Bounded workstation identity layer. It consumes accepted footprints only;
// it never changes plan geometry, cutaways, reflection, or Camera v2.
const m = Object.freeze({
  top: new THREE.MeshStandardMaterial({ color: 0xaa8257, roughness: 0.8 }),
  edge: new THREE.MeshStandardMaterial({ color: 0x6f4f32, roughness: 0.76, metalness: 0.02 }),
  grain: new THREE.MeshStandardMaterial({ color: 0x785335, roughness: 0.88 }),
  black: new THREE.MeshStandardMaterial({ color: 0x202423, roughness: 0.58, metalness: 0.32 }),
  cabinet: new THREE.MeshStandardMaterial({ color: 0x242625, roughness: 0.76, metalness: 0.08 }),
  face: new THREE.MeshStandardMaterial({ color: 0x666158, roughness: 0.82 }),
  void: new THREE.MeshStandardMaterial({ color: 0x141716, roughness: 0.9 }),
  white: new THREE.MeshStandardMaterial({ color: 0xf0eee7, roughness: 0.72 }),
  stitch: new THREE.MeshStandardMaterial({ color: 0xd5d0c7, roughness: 0.9 }),
  chrome: new THREE.MeshStandardMaterial({ color: 0xb9c0bf, roughness: 0.25, metalness: 0.86 }),
  caster: new THREE.MeshStandardMaterial({ color: 0x222525, roughness: 0.68, metalness: 0.13 }),
  monitor: new THREE.MeshStandardMaterial({ color: 0x151918, roughness: 0.43, metalness: 0.2 }),
  display: new THREE.MeshStandardMaterial({ color: 0x1a2c2a, roughness: 0.26, emissive: 0x071411, emissiveIntensity: 0.28 }),
  mic: new THREE.MeshStandardMaterial({ color: 0x171a1a, roughness: 0.54, metalness: 0.28 }),
  grille: new THREE.MeshStandardMaterial({ color: 0x2e3433, roughness: 0.4, metalness: 0.56 }),
  cream: new THREE.MeshStandardMaterial({ color: 0xd8cfbd, roughness: 0.91 }),
  trim: new THREE.MeshStandardMaterial({ color: 0x343736, roughness: 0.58, metalness: 0.18 }),
  stone: new THREE.MeshStandardMaterial({ color: 0x5e625f, roughness: 0.8, metalness: 0.08 }),
  marble: new THREE.MeshStandardMaterial({ color: 0xd8d4ca, roughness: 0.5 }),
  brass: new THREE.MeshStandardMaterial({ color: 0x9f7b46, roughness: 0.32, metalness: 0.74 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0xd9e2dd, roughness: 0.18, transmission: 0.45, transparent: true, opacity: 0.47 }),
  bulb: new THREE.MeshStandardMaterial({ color: 0xe8d8a7, roughness: 0.35, emissive: 0x2b210e, emissiveIntensity: 0.18 }),
  bedUpholstery: new THREE.MeshStandardMaterial({ color: 0x77736d, roughness: 0.94 }),
  bedUpholsteryLight: new THREE.MeshStandardMaterial({ color: 0x89847d, roughness: 0.96 }),
  bedInterior: new THREE.MeshStandardMaterial({ color: 0x242725, roughness: 0.9 }),
  mattress: new THREE.MeshStandardMaterial({ color: 0xe5e1d8, roughness: 0.98 }),
  sheet: new THREE.MeshStandardMaterial({ color: 0xd4cab9, roughness: 0.99 }),
  duvet: new THREE.MeshStandardMaterial({ color: 0xf0ede5, roughness: 1 }),
  beddingSeam: new THREE.MeshStandardMaterial({ color: 0xcfc8bc, roughness: 1 }),
  alexaBand: new THREE.MeshStandardMaterial({ color: 0x3d7180, roughness: 0.4, metalness: 0.18, emissive: 0x092b35, emissiveIntensity: 0.26 }),
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

function footprint(data, id) {
  const item = data.blockers.find((blocker) => blocker.id === id)
  return item ? item.renderFootprint ?? item.sourceFootprint : null
}

function annotation(id) {
  const item = geometryScene.inspection_annotations.objects.find((object) => object.id === id)
  if (!item?.rect_gu) return null
  return Object.fromEntries(Object.entries(item.rect_gu).map(([key, value]) => [key, parseRational(value)]))
}

function addBrayaBed(world, data) {
  const f = footprint(data, 'bedroom.bed')
  if (!f) return
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
  const main = footprint(data, 'bedroom.desk_main')
  const returnDesk = footprint(data, 'bedroom.desk_return')
  if (!main || !returnDesk) return
  const topZ = 102.2
  const mainX = main.x + main.w / 2
  const mainY = main.y + main.h / 2
  // Product dimensions are intentionally visible: the clear-wall main work
  // surface is 31.49in deep, while this return is only 15.74in (half depth).
  // Its inner edge remains joined to the main desk; no plan-space anchor moves.
  const returnDepth = Math.min(returnDesk.w, main.h * 15.74 / 31.49)
  const returnTop = {
    x: returnDesk.x + returnDesk.w - returnDepth,
    y: returnDesk.y,
    w: returnDepth,
    h: returnDesk.h,
  }
  const returnX = returnTop.x + returnTop.w / 2
  const returnY = returnDesk.y + returnDesk.h / 2

  // Light brown manufactured wood and a substantial black storage section are
  // the key product split. Vertical grain bands keep the laminate from reading
  // like a flat, generic gray slab.
  roundedBox(world, main.w, main.h, 4.4, mainX, mainY, topZ, m.top, 'Burgener light-brown main worktop', 2.4)
  roundedBox(world, returnTop.w, returnTop.h, 4.4, returnX, returnY, topZ, m.top, 'Burgener thinner light-brown return worktop', 2.4)
  box(world, main.w, 2.2, 1.2, mainX, main.y + 1.1, 99.8, m.edge, 'Burgener main front edge')
  box(world, 2.2, returnTop.h, 1.2, returnTop.x + returnTop.w - 1.1, returnY, 99.8, m.edge, 'Burgener return edge')
  for (let index = 1; index < 18; index += 1) {
    const x = main.x + index * main.w / 18
    box(world, 0.48, main.h - 4, 0.22, x, mainY, 104.52, m.grain, 'Burgener vertical wood grain mark')
  }
  for (let index = 1; index < 7; index += 1) {
    const x = returnTop.x + index * returnTop.w / 7
    box(world, 0.36, returnTop.h - 5, 0.22, x, returnY, 104.52, m.grain, 'Burgener return wood grain mark')
  }

  for (const x of [main.x + 8, main.x + main.w - 8]) for (const y of [main.y + 6.5, main.y + main.h - 6.5]) {
    box(world, 3.8, 3.8, 96, x, y, 48, m.black, 'Burgener rectangular steel leg')
  }
  box(world, main.w - 14, 3.1, 7, mainX, main.y + 6, 91, m.black, 'Burgener black front apron')
  box(world, 3.1, main.h - 12, 7, main.x + main.w - 7, mainY, 91, m.black, 'Burgener side apron')

  // The cabinet is a continuous supporting mass under the entire thin return;
  // this explicitly removes the previously unsupported floating desk slab.
  const cabinetY = returnTop.y + 4
  const cabinetLength = returnTop.h - 8
  const cabinetCenter = cabinetY + cabinetLength / 2
  const faceX = returnTop.x + returnTop.w - 0.65
  box(world, returnTop.w - 1.4, cabinetLength, 92, returnX, cabinetCenter, 48, m.cabinet, 'Burgener full-length black cubby and file-drawer mass')
  const bay = (cabinetLength - 18) / 3
  for (const index of [0, 1, 2]) {
    const y = cabinetY + 4 + index * (bay + 5)
    if (index === 0) {
      box(world, 1.35, bay, 35, faceX, y + bay / 2, 67, m.void, 'Burgener open cubby')
      box(world, 1.75, bay - 4, 1.3, faceX - 0.65, y + bay / 2, 84, m.face, 'Burgener cubby shelf')
    } else {
      box(world, 1.8, bay - 2, 31, faceX, y + bay / 2, 48, m.face, 'Burgener file drawer face')
      box(world, 2.6, Math.min(15, bay * 0.34), 1.7, faceX + 0.6, y + bay / 2, 48, m.black, 'Burgener drawer pull')
    }
  }
}

function addHomeZeerChair(world, data) {
  const f = footprint(data, 'bedroom.chair')
  if (!f) return
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
  const f = annotation('bedroom.monitor')
  if (!f) return
  const cx = f.x + f.w / 2
  const panelY = f.y + f.h * 0.47
  const top = 104.4
  const panelH = f.w * 9 / 16
  // One 27-inch 16:9 Samsung panel, neck, and stand entirely above desk top.
  ellipsoid(world, f.w * 0.32, 10, 1.9, cx, f.y + f.h * 0.28, top + 1.4, m.monitor, 'Samsung Odyssey oval stand base')
  box(world, 5.4, 3.2, 18, cx, f.y + f.h * 0.48, top + 10, m.monitor, 'Samsung Odyssey stand neck')
  box(world, f.w, 2.8, panelH, cx, panelY, top + 17 + panelH / 2, m.monitor, 'Samsung Odyssey G5 27-inch panel')
  box(world, f.w * 0.94, 0.45, panelH * 0.91, cx, panelY - 1.63, top + 17 + panelH / 2, m.display, 'Samsung Odyssey display face')
}

function addBlueYeti(world) {
  const f = annotation('bedroom.microphone')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  // Accepted raw anchor intentionally becomes the user's right with reflection.
  cylinderZ(world, 4.2, 4.9, 1.7, cx, cy, z + 0.85, m.mic, 'Blue Yeti small circular base')
  cylinderZ(world, 3.45, 3.45, 15, cx, cy, z + 9.4, m.grille, 'Blue Yeti small capsule grille')
  cylinderZ(world, 3.1, 3.45, 4.8, cx, cy, z + 3.3, m.mic, 'Blue Yeti small lower body')
  ellipsoid(world, 6.8, 6.8, 4.2, cx, cy, z + 17.2, m.grille, 'Blue Yeti small rounded grille cap')
  for (const offset of [-4.2, 4.2]) {
    rod(world, new THREE.Vector3(cx + offset, cy, z + 3), new THREE.Vector3(cx + offset, cy, z + 14.5), 0.82, m.mic, 'Blue Yeti small side yoke')
    cylinderZ(world, 1.2, 1.2, 1.4, cx + offset, cy - 3.2, z + 10.4, m.grille, 'Blue Yeti small yoke knob')
  }
  for (const band of [z + 9, z + 12.5]) box(world, 6.2, 0.45, 0.5, cx, cy - 3.4, band, m.mic, 'Blue Yeti small grille band')
}

function addDrumLamp(world) {
  // The raw right anchor presents on the room's left after the accepted
  // reflection. Review established that the drum lamp belongs there.
  const f = annotation('bedroom.lamp_l5')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  // Keep the left drum lamp upright and opaque: a short, faceted base and
  // a broad hard white fabric shade prevent the old lantern silhouette.
  cylinderZ(world, 8.7, 7.2, 11, cx, cy, z + 5.5, m.stone, 'L2 faceted gray lamp base', 6)
  cylinderZ(world, 2.4, 2.4, 8, cx, cy, z + 14.5, m.trim, 'L2 short centered lamp neck', 12)
  cylinderZ(world, 14.4, 13.1, 32, cx, cy, z + 34.5, m.cream, 'L2 hard white fabric drum shade', 32)
  cylinderZ(world, 13.3, 13.3, 1.1, cx, cy, z + 18.7, m.trim, 'L2 dark lower shade trim', 32)
  cylinderZ(world, 14.55, 14.55, 1.1, cx, cy, z + 50.6, m.trim, 'L2 dark upper shade trim', 32)
}

function cylinderX(world, left, right, radius, y, z, material, name, segments = 16) {
  const item = mesh(world, new THREE.CylinderGeometry(radius, radius, right - left, segments), material, name)
  item.rotation.z = -Math.PI / 2
  item.position.set((left + right) / 2, y, z)
  return item
}

function addEpsonProjector(world) {
  const f = annotation('bedroom.projector')
  // The annotation supplies the accepted y anchor. The thin-return x extent
  // is reproduced here without mutating that accepted plan-space rectangle.
  if (!f) return
  const returnRight = 60.22
  const returnDepth = 46.38 * 15.74 / 31.49
  const cx = returnRight - returnDepth / 2
  const cy = f.y + f.h / 2
  const z = 106.2
  const bodyW = Math.min(21.4, returnDepth - 1.2)
  const bodyD = 24.4
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
  const headphones = annotation('bedroom.headphones')
  if (headphones) {
    const group = new THREE.Group()
    group.name = 'Desk headphones fixed world-space assembly'
    group.position.set(headphones.x + headphones.w / 2, headphones.y + headphones.h / 2, 105.5)
    world.add(group)
    const band = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-5.2, 0, 0), new THREE.Vector3(-5.2, 0, 7.4),
      new THREE.Vector3(0, 0, 11.1), new THREE.Vector3(5.2, 0, 7.4), new THREE.Vector3(5.2, 0, 0),
    ])
    mesh(group, new THREE.TubeGeometry(band, 16, 1.0, 10, false), m.mic, 'Desk headphones shaped headband')
    ellipsoid(group, 4.2, 3.4, 6.8, -5.2, 0, 1.6, m.grille, 'Desk headphones left ear cup')
    ellipsoid(group, 4.2, 3.4, 6.8, 5.2, 0, 1.6, m.grille, 'Desk headphones right ear cup')
  }

  const alexa = annotation('bedroom.alexa')
  if (alexa) {
    const group = new THREE.Group()
    group.name = 'Desk Alexa fixed world-space assembly'
    group.position.set(alexa.x + alexa.w / 2, alexa.y + alexa.h / 2, 105.5)
    world.add(group)
    cylinderZ(group, 4.2, 4.7, 5.2, 0, 0, 2.6, m.cabinet, 'Desk Alexa stationary puck')
    cylinderZ(group, 4.28, 4.28, 0.55, 0, 0, 5.5, m.alexaBand, 'Desk Alexa blue top ring')
  }
}

function addMarblePendantLamp(world) {
  // The raw left anchor presents at the right desk corner after reflection.
  // The real marble lamp sits diagonally at that corner, not square to the top.
  const f = annotation('bedroom.lamp_l2')
  if (!f) return
  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const z = 105.4
  const lamp = new THREE.Group()
  lamp.name = 'L5 diagonal marble pendant lamp assembly'
  lamp.position.set(cx, cy, z)
  lamp.rotation.z = Math.PI / 4
  world.add(lamp)
  box(lamp, 22, 13, 4.2, 0, 0, 2.1, m.marble, 'L5 white marble rectangular base')
  cylinderZ(lamp, 1.45, 1.45, 47, 4, 0, 27.7, m.brass, 'L5 thin brass stem', 12)
  const hook = new THREE.CatmullRomCurve3([
    new THREE.Vector3(4, 0, 50), new THREE.Vector3(4, 0, 62),
    new THREE.Vector3(-5, 0, 65), new THREE.Vector3(-7, 0, 57),
  ])
  mesh(lamp, new THREE.TubeGeometry(hook, 20, 1.45, 10, false), m.brass, 'L5 curved brass top hook')
  cylinderZ(lamp, 8.2, 8.2, 29, -7, 0, 42, m.glass, 'L5 seeded-glass hanging cylinder', 20)
  ellipsoid(lamp, 5.8, 5.8, 9.5, -7, 0, 42, m.bulb, 'L5 visible hanging bulb', 14)
  cylinderZ(lamp, 4.5, 4.5, 3, -7, 0, 58, m.brass, 'L5 brass glass cap', 16)
}

export function addBedroomDesignPassV1(world, data) {
  // Keep the recovered workstation independent of future bedding experiments.
  addBurgenerDesk(world, data)
  addHomeZeerChair(world, data)
  addOdysseyMonitor(world)
  addBlueYeti(world)
  addDrumLamp(world)
  addMarblePendantLamp(world)
  addEpsonProjector(world)
  addDeskAccessories(world)
  addBrayaBed(world, data)
}
