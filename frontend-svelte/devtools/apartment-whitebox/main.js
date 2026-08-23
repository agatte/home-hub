import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import geometryScene from './generated/geometry-scene.json'
import {
  adaptGeometryScene,
  horizontalFovToVertical,
  perspectiveCandidate,
  topDownTruthView,
} from './adapter.js'
import './styles.css'

const data = adaptGeometryScene(geometryScene)

// Measured vertical inspection authority.
const inspectionCeilingTopZ = 364.43
const originalWallTopZ = Math.max(...data.walls.map((wall) => wall.zMax))

for (const wall of data.walls) {
  if (Math.abs(wall.zMax - originalWallTopZ) < 0.001) {
    wall.zMax = inspectionCeilingTopZ
  }
}

const measuredApertureZ = new Map([
  ['bedroom_window_left',  { min: 81.36, max: 311.88 }],
  ['bedroom_window_right', { min: 81.36, max: 311.88 }],
  ['living_window_left',   { min: 81.36, max: 311.88 }],
  ['living_window_right',  { min: 81.36, max: 311.88 }],

      ['balcony_door', { min: 0, max: 267.81 }],
  ['bedroom_door',      { min: 0, max: 271.20 }],
  ['bathroom_door',     { min: 0, max: 271.20 }],
  ['laundry_door',      { min: 0, max: 271.20 }],
  ['water_heater_door', { min: 0, max: 271.20 }],
  ['front_door',        { min: 0, max: 271.20 }],
  ['closet_opening',    { min: 0, max: 271.20 }],
])

for (const opening of data.openings) {
  const measured = measuredApertureZ.get(opening.sourceApertureId)
  if (!measured) continue

  opening.void = { ...measured }

  if (!opening.closureFootprint) continue

  opening.solidRanges = opening.kind === 'window'
    ? [
        { min: 0, max: measured.min },
        { min: measured.max, max: inspectionCeilingTopZ },
      ]
    : [
        { min: measured.max, max: inspectionCeilingTopZ },
      ]
}

data.bounds.maxZ = inspectionCeilingTopZ

const canvas = document.querySelector('#whitebox-canvas')
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
renderer.setClearColor(0xdfe4e5, 1)
renderer.outputColorSpace = THREE.SRGBColorSpace

const scene = new THREE.Scene()
// This group owns only a reversible display transform for Top-down truth.
// GeometryScene coordinates remain unchanged in `data` and in mesh buffers.
const world = new THREE.Group()
scene.add(world)
scene.add(new THREE.HemisphereLight(0xf6f8f6, 0x7d8b89, 2.2))
const key = new THREE.DirectionalLight(0xffffff, 2.1)
key.position.set(650, 900, 1200)
scene.add(key)

const perspectiveCamera = new THREE.PerspectiveCamera(40, 1, 1, 10000)
perspectiveCamera.up.set(0, 0, 1)

// Camera v2 geometry stays in accepted plan coordinates. The accepted
// perspective needs a presentation-only horizontal projection reflection
// so the displayed 3D view has the same chirality as the verified plan.
function setPerspectivePresentationReflection(enabled) {
  perspectiveCamera.updateProjectionMatrix()
  if (enabled) perspectiveCamera.projectionMatrix.elements[0] *= -1
  perspectiveCamera.projectionMatrixInverse.copy(perspectiveCamera.projectionMatrix).invert()
}
const truthCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10000)
truthCamera.up.set(0, -1, 0)
let activeCamera = perspectiveCamera
let activeView = 'candidate'
let presets = {}
const controls = new OrbitControls(activeCamera, renderer.domElement)
controls.enableDamping = true
controls.dampingFactor = 0.08
const overlayGroups = {
  rooms: new THREE.Group(), fixtures: new THREE.Group(), openings: new THREE.Group(), architecture: new THREE.Group(),
  primaryBlockers: new THREE.Group(), secondaryBlockers: new THREE.Group(), objectLabels: new THREE.Group(),
  plants: new THREE.Group(),
  floorTreatments: new THREE.Group(),
}
Object.values(overlayGroups).forEach((group) => world.add(group))
const inspectable = []
const raycaster = new THREE.Raycaster()
raycaster.params.Line.threshold = 10
const pointer = new THREE.Vector2()
const selection = document.querySelector('#selection')
const cutawayStatus = document.querySelector('#cutaway-status')
const cutawayCandidates = new Map(data.presentation.cutawayCandidates.map((candidate) => [candidate.id, candidate]))
let activeCutaway = cutawayCandidates.get('accepted_north')
const cutawayUniforms = {
  cutawayLip: { value: data.presentation.cutaway.lipHeightGu },
  cutawayCount: { value: 0 },
  cutawayMinX0: { value: 0 }, cutawayMaxX0: { value: 0 }, cutawayMinY0: { value: 0 }, cutawayMaxY0: { value: 0 },
  cutawayMinX1: { value: 0 }, cutawayMaxX1: { value: 0 }, cutawayMinY1: { value: 0 }, cutawayMaxY1: { value: 0 },
}

function shapeFromRings(outer, holes = []) {
  const shape = new THREE.Shape()
  shape.moveTo(outer[0].x, outer[0].y)
  outer.slice(1).forEach((point) => shape.lineTo(point.x, point.y))
  for (const holeRing of holes) {
    const hole = new THREE.Path()
    hole.moveTo(holeRing[0].x, holeRing[0].y)
    holeRing.slice(1).forEach((point) => hole.lineTo(point.x, point.y))
    shape.holes.push(hole)
  }
  return shape
}

function extrusionFromRings(outer, holes, zMin, zMax) {
  const geometry = new THREE.ExtrudeGeometry(shapeFromRings(outer, holes), {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 1,
  })
  geometry.translate(0, 0, zMin)
  return geometry
}

function ellipseExtrusion(x, y, w, h, zMin, zMax) {
  const shape = new THREE.Shape()
  shape.absellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, Math.PI * 2, false, 0)
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: zMax - zMin,
    bevelEnabled: false,
    curveSegments: 16,
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

function blockerInspection(blocker, primitive) {
  return {
    renderObjectType: blocker.renderObjectType ?? 'provisional physical blocker',
    objectId: blocker.id,
    acceptedSourceFootprint: `${blocker.id} ${JSON.stringify(blocker.sourceFootprint)}`,
    renderedFootprint: JSON.stringify(blocker.renderFootprint ?? blocker.sourceFootprint),
    blockerRecipe: blocker.recipe,
    blockerPrimitive: primitive.name,
    provisionalZRangeGu: `${primitive.zMin}–${primitive.zMax}`,
    xyStatus: blocker.xy_source,
    zStatus: 'provisional inspection',
    silhouetteStatus: 'provisional inspection',
  }
}

function addBlockerPrimitive(group, blocker, primitive, material) {
  const renderFootprint = blocker.renderFootprint ?? blocker.sourceFootprint
  const makeMesh = (part, bounds) => {
    let geometry
    if (part.kind === 'ellipsoid') {
      const radiusZ = (part.zMax - part.zMin) / 2
      geometry = new THREE.SphereGeometry(1, 24, 16)
      geometry.scale(bounds.w / 2, bounds.h / 2, radiusZ)
      geometry.translate(
        bounds.x + bounds.w / 2,
        bounds.y + bounds.h / 2,
        part.zMin + radiusZ,
      )
    } else if (part.kind === 'ellipse') {
      geometry = ellipseExtrusion(bounds.x, bounds.y, bounds.w, bounds.h, part.zMin, part.zMax)
    } else {
      geometry = extrusionFromRings([
        { x: bounds.x, y: bounds.y }, { x: bounds.x + bounds.w, y: bounds.y },
        { x: bounds.x + bounds.w, y: bounds.y + bounds.h }, { x: bounds.x, y: bounds.y + bounds.h },
      ], [], part.zMin, part.zMax)
    }
    const mesh = new THREE.Mesh(geometry, material)
    mesh.userData.inspection = blockerInspection(blocker, part)
    group.add(mesh)
    inspectable.push(mesh)
  }
  if (primitive.kind !== 'open_frame') {
    makeMesh(primitive, primitiveBounds(renderFootprint, primitive))
    return
  }
  const { x, y, w, h } = renderFootprint
  const t = primitive.thickness
  // Sparse rails deliberately preserve the shower's open enclosure reading.
  for (const rail of [
    { kind: 'box', name: `${primitive.name} west rail`, x: 0, y: 0, w: t, h: 1, zMin: primitive.zMin, zMax: primitive.zMax },
    { kind: 'box', name: `${primitive.name} east rail`, x: 1 - t, y: 0, w: t, h: 1, zMin: primitive.zMin, zMax: primitive.zMax },
    { kind: 'box', name: `${primitive.name} north rail`, x: 0, y: 1 - t, w: 1, h: t, zMin: primitive.zMin, zMax: primitive.zMax },
  ]) makeMesh(rail, primitiveBounds({ x, y, w, h }, rail))
}

function textSprite(text, color = '#26383d') {
  const canvas = document.createElement('canvas')
  const context = canvas.getContext('2d')
  context.font = '600 30px system-ui'
  const width = Math.ceil(context.measureText(text).width) + 22
  canvas.width = width
  canvas.height = 46
  context.font = '600 30px system-ui'
  context.fillStyle = 'rgba(248, 250, 249, 0.90)'
  context.fillRect(0, 0, width, 46)
  context.fillStyle = color
  context.fillText(text, 11, 33)
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false, transparent: true }))
  sprite.scale.set(width * 0.85, 39, 1)
  return sprite
}

function metadataText(metadata) {
  return Object.entries(metadata)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join('\n')
}

function updateSelection(object) {
  selection.textContent = object ? metadataText(object.userData.inspection) : 'Hover or click a wall, opening, or blocker for source metadata.'
}

function boundsUniforms(bounds) {
  return {
    minX: { value: bounds.minX }, maxX: { value: bounds.maxX },
    minY: { value: bounds.minY }, maxY: { value: bounds.maxY },
  }
}

function makeWallMaterial() {
  const material = new THREE.MeshStandardMaterial({
    color: 0xd9ddda, roughness: 0.88, metalness: 0, transparent: true, depthWrite: true, side: THREE.DoubleSide,
  })
  const bedroomUniforms = boundsUniforms(data.presentation.bedroom.faceBounds)
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, {
      ...cutawayUniforms,
      bedroomBase: { value: data.presentation.bedroom.solidBaseHeightGu },
      bedroomOpacity: { value: data.presentation.bedroom.upperOpacity },
      ...Object.fromEntries(Object.entries(bedroomUniforms).map(([key, value]) => [`bedroom${key[0].toUpperCase()}${key.slice(1)}`, value])),
    })
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 whiteboxWorldPosition;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nwhiteboxWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 whiteboxWorldPosition;
uniform float cutawayLip;
uniform int cutawayCount;
uniform float cutawayMinX0; uniform float cutawayMaxX0; uniform float cutawayMinY0; uniform float cutawayMaxY0;
uniform float cutawayMinX1; uniform float cutawayMaxX1; uniform float cutawayMinY1; uniform float cutawayMaxY1;
uniform float bedroomBase; uniform float bedroomOpacity;
uniform float bedroomMinX; uniform float bedroomMaxX; uniform float bedroomMinY; uniform float bedroomMaxY;`)
      .replace('#include <color_fragment>', `#include <color_fragment>
bool inCutaway = cutawayCount > 0 && whiteboxWorldPosition.x >= cutawayMinX0 && whiteboxWorldPosition.x <= cutawayMaxX0
  && whiteboxWorldPosition.y >= cutawayMinY0 && whiteboxWorldPosition.y <= cutawayMaxY0;
inCutaway = inCutaway || (cutawayCount > 1 && whiteboxWorldPosition.x >= cutawayMinX1 && whiteboxWorldPosition.x <= cutawayMaxX1
  && whiteboxWorldPosition.y >= cutawayMinY1 && whiteboxWorldPosition.y <= cutawayMaxY1);
if (inCutaway && whiteboxWorldPosition.z > cutawayLip) discard;
bool onBedroomFace = whiteboxWorldPosition.x >= bedroomMinX && whiteboxWorldPosition.x <= bedroomMaxX
  && abs(whiteboxWorldPosition.y - bedroomMinY) < 0.001 && whiteboxWorldPosition.z > bedroomBase;
if (onBedroomFace) diffuseColor.a = bedroomOpacity;

bool inEntryTallCabinetFalseWall =
  whiteboxWorldPosition.x >= 359.64 &&
  whiteboxWorldPosition.x <= 444.39 &&
  whiteboxWorldPosition.y >= 1041.315 &&
  whiteboxWorldPosition.y <= 1085.385;

if (inEntryTallCabinetFalseWall) discard;`)
  }
  return material
}

const apartmentFloorMaterial = new THREE.MeshStandardMaterial({ color: 0xbfc6c5, roughness: 1 })
const balconyFloorMaterial = new THREE.MeshStandardMaterial({ color: 0xaeb8b7, roughness: 1 })
for (const slab of data.slabs) {
  const mesh = new THREE.Mesh(
    extrusionFromRings(slab.ring, [], slab.zMin, slab.zMax),
    slab.kind === 'balcony_floor_slab' ? balconyFloorMaterial : apartmentFloorMaterial,
  )
  world.add(mesh)
}

const wallMaterial = makeWallMaterial()
for (const wall of data.walls) {
  const mesh = new THREE.Mesh(extrusionFromRings(wall.outer, wall.holes, wall.zMin, wall.zMax), wallMaterial)
  mesh.userData.inspection = wall.inspection
  world.add(mesh)
  inspectable.push(mesh)
  const centroid = wall.outer.reduce((total, point) => ({ x: total.x + point.x, y: total.y + point.y }), { x: 0, y: 0 })
  const id = textSprite(wall.id.replace('geometry_scene.extrusion.', ''), '#35525b')
  id.position.set(centroid.x / wall.outer.length, centroid.y / wall.outer.length, wall.zMax + 6)
  overlayGroups.architecture.add(id)
}

// presentation-only kitchen east wall skin
// Covers small canonical contour jogs that become distracting fins in perspective.
// Canonical GeometryScene coordinates remain unchanged; Top-down truth hides this skin.
const kitchenWallSkin = new THREE.Group()
const kitchenWallSkinMesh = new THREE.Mesh(
  extrusionFromRings([
    { x: 980.50, y: 755.90 },
    { x: 981.30, y: 755.90 },
    { x: 981.30, y: 1230.27 },
    { x: 980.50, y: 1230.27 },
  ], [], 0, Math.max(...data.walls.map((wall) => wall.zMax))),
  wallMaterial,
)
kitchenWallSkin.add(kitchenWallSkinMesh)
world.add(kitchenWallSkin)
const openingClosureMaterial = new THREE.MeshStandardMaterial({ color: 0xd9ddda, roughness: 0.88, side: THREE.DoubleSide })

for (const opening of data.openings) {
  for (const range of opening.solidRanges) {
    world.add(new THREE.Mesh(
      extrusionFromRings(opening.closureFootprint, [], range.min, range.max),
      openingClosureMaterial,
    ))
  }
  const [first, last] = opening.segment
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(first.x, first.y, 4), new THREE.Vector3(last.x, last.y, 4)]),
    new THREE.LineBasicMaterial({ color: 0x44656d, transparent: true, opacity: 0.01 }),
  )
  line.userData.inspection = opening.inspection
  // Hit target remains available even when labels are hidden; it has no
  // footprint or wall effect and exists only for source inspection.
  world.add(line)
  inspectable.push(line)
  const openingLabel = textSprite(opening.sourceApertureId, '#435f67')
  openingLabel.position.set((first.x + last.x) / 2, (first.y + last.y) / 2, 12)
  overlayGroups.openings.add(openingLabel)
  const openingId = textSprite(opening.id.replace('geometry_scene.opening.', ''), '#35525b')
  openingId.position.set((first.x + last.x) / 2, (first.y + last.y) / 2, 25)
  overlayGroups.architecture.add(openingId)
}

// measured balcony door panel visual
const balconyDoor = data.openings.find((opening) => opening.sourceApertureId === 'balcony_door')
if (balconyDoor?.closureFootprint) {
  const xs = balconyDoor.closureFootprint.map((point) => point.x)
  const ys = balconyDoor.closureFootprint.map((point) => point.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)

  const doorWidth = maxX - minX
  const glassWidth = 81.36 // 24in
  const sideRail = Math.max(0, (doorWidth - glassWidth) / 2)
  const doorTop = 267.81 // 79in
  const glassBottom = 40.68 // 12in
  const glassTop = 252.56 // 4.5in below top

  const frameMaterial = new THREE.MeshStandardMaterial({ color: 0xd5d7d4, roughness: 0.9 })
  const glassMaterial = new THREE.MeshStandardMaterial({ color: 0xaab8bd, transparent: true, opacity: 0.32, roughness: 0.35, side: THREE.DoubleSide })

  const addDoorPart = (x0, x1, z0, z1, material) => {
    if (x1 <= x0 || z1 <= z0) return
    world.add(new THREE.Mesh(
      extrusionFromRings([
        { x: x0, y: minY },
        { x: x1, y: minY },
        { x: x1, y: maxY },
        { x: x0, y: maxY },
      ], [], z0, z1),
      material,
    ))
  }

  addDoorPart(minX, maxX, 0, glassBottom, frameMaterial)
  addDoorPart(minX, maxX, glassTop, doorTop, frameMaterial)
  addDoorPart(minX, minX + sideRail, glassBottom, glassTop, frameMaterial)
  addDoorPart(maxX - sideRail, maxX, glassBottom, glassTop, frameMaterial)
  addDoorPart(minX + sideRail, maxX - sideRail, glassBottom, glassTop, glassMaterial)
}
for (const room of data.rooms) {
  const label = textSprite(room.label, '#182f35')
  label.position.set(room.position.x, room.position.y, 14)
  overlayGroups.rooms.add(label)
}

const measuredLivingRug = Object.freeze({
  id: 'living.rug.measured',
  // 9 ft x 6 ft at the apartment's calibrated ~3.39 GU/in scale.
  // Rotated 90° and nudged toward the couch.
  x: 580.00,
  y: 234.34,
  w: 244.08,
  h: 366.12,
})

const rugMaterial = new THREE.MeshStandardMaterial({
  color: 0x8f9c91,
  roughness: 1,
  metalness: 0,
  transparent: true,
  opacity: 0.72,
})

{
  const { x, y, w, h } = measuredLivingRug
  const mesh = new THREE.Mesh(
    extrusionFromRings([
      { x, y },
      { x: x + w, y },
      { x: x + w, y: y + h },
      { x, y: y + h },
    ], [], 0.5, 2),
    rugMaterial,
  )

  mesh.userData.inspection = {
    renderObjectType: 'measured non-blocking floor treatment',
    objectId: measuredLivingRug.id,
    dimensions: '108in x 72in',
    placement: 'under white chair and coffee table; excluded from couch footprint',
    status: 'provisional visual placement',
  }

  overlayGroups.floorTreatments.add(mesh)
  inspectable.push(mesh)
}

for (const fixture of data.fixtureDebugAids) {
  const { x, y, w, h } = fixture.rect
  const material = new THREE.MeshBasicMaterial({ color: 0xf7f9f8, transparent: true, opacity: 0.72, depthWrite: false })
  const mesh = new THREE.Mesh(extrusionFromRings([
    { x, y }, { x: x + w, y }, { x: x + w, y: y + h }, { x, y: y + h },
  ], [], 1, 28), material)
  mesh.userData.inspection = {
    renderObjectType: 'fixture debug aid', geometrySceneObjectId: fixture.id, source: fixture.source,
    classification: fixture.classification,
  }
  overlayGroups.fixtures.add(mesh)
  const label = textSprite(`${fixture.label} · debug`, '#705647')
  label.position.set(x + w / 2, y + h / 2, 32)
  overlayGroups.fixtures.add(label)
}

const blockerMaterials = Object.freeze({
  bed: new THREE.MeshStandardMaterial({ color: 0xc9b8a7, roughness: 0.94, metalness: 0 }),
  seating: new THREE.MeshStandardMaterial({ color: 0xaeb9c9, roughness: 0.94, metalness: 0 }),
  furniture: new THREE.MeshStandardMaterial({ color: 0xb7c5bf, roughness: 0.94, metalness: 0 }),
  fixture: new THREE.MeshStandardMaterial({ color: 0xc4c0b6, roughness: 0.94, metalness: 0 }),
  secondary: new THREE.MeshStandardMaterial({ color: 0xb8b0c4, roughness: 0.94, metalness: 0 }),
  fallback: new THREE.MeshStandardMaterial({ color: 0xd9dfde, roughness: 0.94, metalness: 0 }),
})

function materialForBlocker(blocker) {
  if (blocker.scope === 'secondary') return blockerMaterials.secondary
  if (blocker.id === 'bedroom.bed') return blockerMaterials.bed
  if (/(chair|stool|couch)/.test(blocker.id)) return blockerMaterials.seating
  if (/(desk|table|stand|dresser|island|cabinet)/.test(blocker.id)) return blockerMaterials.furniture
  if (/(stove|fridge|pantry|vanity|toilet|shower|laundry|water_heater)/.test(blocker.id)) return blockerMaterials.fixture
  return blockerMaterials.fallback
}
const plantStandMaterial = new THREE.MeshStandardMaterial({ color: 0x85796e, roughness: 0.96, metalness: 0 })
const plantPotMaterial = new THREE.MeshStandardMaterial({ color: 0xa99482, roughness: 0.96, metalness: 0 })
const plantFoliageMaterial = new THREE.MeshStandardMaterial({ color: 0x788a70, roughness: 0.98, metalness: 0 })

const couchForPlants = data.blockers.find((blocker) => blocker.id === 'living.couch')
const couchPlantFootprint = couchForPlants.renderFootprint ?? couchForPlants.sourceFootprint
const couchSouth = couchPlantFootprint.y + couchPlantFootprint.h

function standFramePrimitives(topZ) {
  const t = .06
  const railZ = 2.2
  return [
    { kind: 'box', name: 'northwest leg', x: 0, y: 0, w: t, h: t, zMin: railZ, zMax: topZ - 2.2 },
    { kind: 'box', name: 'northeast leg', x: 1 - t, y: 0, w: t, h: t, zMin: railZ, zMax: topZ - 2.2 },
    { kind: 'box', name: 'southwest leg', x: 0, y: 1 - t, w: t, h: t, zMin: railZ, zMax: topZ - 2.2 },
    { kind: 'box', name: 'southeast leg', x: 1 - t, y: 1 - t, w: t, h: t, zMin: railZ, zMax: topZ - 2.2 },
    { kind: 'box', name: 'bottom north rail', x: 0, y: 0, w: 1, h: t, zMin: 0, zMax: railZ },
    { kind: 'box', name: 'bottom south rail', x: 0, y: 1 - t, w: 1, h: t, zMin: 0, zMax: railZ },
    { kind: 'box', name: 'bottom west rail', x: 0, y: 0, w: t, h: 1, zMin: 0, zMax: railZ },
    { kind: 'box', name: 'bottom east rail', x: 1 - t, y: 0, w: t, h: 1, zMin: 0, zMax: railZ },
    { kind: 'box', name: 'thin top', x: 0, y: 0, w: 1, h: 1, zMin: topZ - 2.2, zMax: topZ },
  ]
}
const plantVisuals = [
  { id: 'living.snake_plant', sourceLabel: 'Snake plant', recipe: 'measured_living_plant_stand_tall', renderObjectType: 'visual-only plant group', source: 'user measurements', sourceFootprint: { x: 917.45, y: couchSouth + 40.68, w: 33.36, h: 33.36 }, renderFootprint: { x: 917.45, y: couchSouth + 40.68, w: 33.36, h: 33.36 }, primitives: [
    ...standFramePrimitives(93.39),
    { kind: 'ellipse', name: 'pot', x: .18, y: .18, w: .64, h: .64, zMin: 93.39, zMax: 119.16 },
    { kind: 'ellipsoid', name: 'foliage lower', x: .08, y: .08, w: .84, h: .84, zMin: 114, zMax: 175 },
    { kind: 'ellipsoid', name: 'foliage upper', x: .24, y: .18, w: .52, h: .64, zMin: 150, zMax: 205 },
  ]},
  { id: 'living.zz_plant', sourceLabel: 'ZZ plant', recipe: 'measured_living_plant_stand_short', renderObjectType: 'visual-only plant group', source: 'user measurements', sourceFootprint: { x: 865.24, y: couchSouth + 23.73, w: 29.36, h: 29.36 }, renderFootprint: { x: 865.24, y: couchSouth + 23.73, w: 29.36, h: 29.36 }, primitives: [
    ...standFramePrimitives(80.07),
    { kind: 'ellipse', name: 'pot', x: .18, y: .18, w: .64, h: .64, zMin: 80.07, zMax: 104.71 },
    { kind: 'ellipsoid', name: 'foliage lower', x: .05, y: .05, w: .90, h: .90, zMin: 101, zMax: 148 },
    { kind: 'ellipsoid', name: 'foliage upper', x: .20, y: .16, w: .60, h: .68, zMin: 130, zMax: 174 },
  ]},
]

for (const plant of plantVisuals) {
  plant.primitives.forEach((primitive, index) => {
    const material = primitive.name === 'pot' ? plantPotMaterial : primitive.name.startsWith('foliage') ? plantFoliageMaterial : plantStandMaterial
    addBlockerPrimitive(overlayGroups.plants, plant, primitive, material)
  })
}
const kitchenUpperCabinets = [
  { id: 'kitchen.cabinet_upper_left', scope: 'primary', sourceLabel: 'Upper cabinet left', source: 'user measurements + kitchen photo', recipe: 'measured_24x13x42', sourceFootprint: { x: 936.43, y: 718.52, w: 44.07, h: 81.36 }, renderFootprint: { x: 936.43, y: 718.52, w: 44.07, h: 81.36 }, primitives: [{ kind: 'box', name: 'cabinet mass', x: 0, y: 0, w: 1, h: 1, zMin: 183.91, zMax: 326.29 }] },
  { id: 'kitchen.cabinet_above_microwave', scope: 'primary', sourceLabel: 'Cabinet above microwave', source: 'user measurements + kitchen photo', recipe: 'measured_29_5x13x23_5', sourceFootprint: { x: 936.43, y: 803.27, w: 44.07, h: 100.01 }, renderFootprint: { x: 936.43, y: 803.27, w: 44.07, h: 100.01 }, primitives: [{ kind: 'box', name: 'cabinet mass', x: 0, y: 0, w: 1, h: 1, zMin: 246.62, zMax: 326.29 }] },
  { id: 'kitchen.cabinet_upper_right', scope: 'primary', sourceLabel: 'Upper cabinet right', source: 'user measurements + kitchen photo', recipe: 'measured_27x13x42', sourceFootprint: { x: 936.43, y: 903.28, w: 44.07, h: 91.53 }, renderFootprint: { x: 936.43, y: 903.28, w: 44.07, h: 91.53 }, primitives: [{ kind: 'box', name: 'cabinet mass', x: 0, y: 0, w: 1, h: 1, zMin: 183.91, zMax: 326.29 }] },
  { id: 'kitchen.cabinet_above_fridge', scope: 'primary', sourceLabel: 'Cabinet above fridge', source: 'user measurements + kitchen photo', recipe: 'measured_36x13x23_5', sourceFootprint: { x: 936.43, y: 995.65, w: 44.07, h: 122.04 }, renderFootprint: { x: 936.43, y: 995.65, w: 44.07, h: 122.04 }, primitives: [{ kind: 'box', name: 'cabinet mass', x: 0, y: 0, w: 1, h: 1, zMin: 246.62, zMax: 326.29 }] },
]
for (const cabinet of kitchenUpperCabinets) {
  const material = materialForBlocker(cabinet)
  cabinet.primitives.forEach((primitive) => addBlockerPrimitive(overlayGroups.primaryBlockers, cabinet, primitive, material))
}
for (const blocker of data.blockers) {
  const group = blocker.scope === 'primary' ? overlayGroups.primaryBlockers : overlayGroups.secondaryBlockers
  const material = materialForBlocker(blocker)
  blocker.primitives.forEach((primitive) => addBlockerPrimitive(group, blocker, primitive, material))
  const label = textSprite(`${blocker.sourceLabel} · provisional`, '#53666b')
  label.position.set(
    blocker.sourceFootprint.x + blocker.sourceFootprint.w / 2,
    blocker.sourceFootprint.y + blocker.sourceFootprint.h / 2,
    Math.max(...blocker.primitives.map((primitive) => primitive.zMax)) + 8,
  )
  overlayGroups.objectLabels.add(label)
}

function bindToggle(selector, group) {
  const input = document.querySelector(selector)
  group.visible = input.checked
  input.addEventListener('change', () => { group.visible = input.checked })
}

bindToggle('#toggle-room-labels', overlayGroups.rooms)
bindToggle('#toggle-fixtures', overlayGroups.fixtures)
bindToggle('#toggle-primary-blockers', overlayGroups.primaryBlockers)
bindToggle('#toggle-secondary-blockers', overlayGroups.secondaryBlockers)
bindToggle('#toggle-object-labels', overlayGroups.objectLabels)
bindToggle('#toggle-opening-labels', overlayGroups.openings)
bindToggle('#toggle-architecture-ids', overlayGroups.architecture)

function setCutaway(id) {
  const candidate = cutawayCandidates.get(id)
  if (!candidate?.available) return
  activeCutaway = candidate
  cutawayUniforms.cutawayCount.value = candidate.targets.length
  for (const [index, target] of candidate.targets.entries()) {
    cutawayUniforms[`cutawayMinX${index}`].value = target.bounds.minX
    cutawayUniforms[`cutawayMaxX${index}`].value = target.bounds.maxX
    cutawayUniforms[`cutawayMinY${index}`].value = target.bounds.minY
    cutawayUniforms[`cutawayMaxY${index}`].value = target.bounds.maxY
  }
  for (let index = candidate.targets.length; index < 2; index += 1) {
    cutawayUniforms[`cutawayMinX${index}`].value = 0
    cutawayUniforms[`cutawayMaxX${index}`].value = 0
    cutawayUniforms[`cutawayMinY${index}`].value = 0
    cutawayUniforms[`cutawayMaxY${index}`].value = 0
  }
  document.querySelector('#cutaway-select').value = id
  const targets = candidate.targets.map((target) => `${target.wallId} / ${target.faceId}`)
  cutawayStatus.textContent = `${candidate.classification}\n${data.presentation.cutaway.lipHeightGu} GU lip (${data.presentation.cutaway.lipStatus})\n${targets.length ? targets.join('\n') : 'No wall/face targets'}`
}

document.querySelector('#cutaway-select').addEventListener('change', (event) => setCutaway(event.target.value))
setCutaway(activeCutaway.id)

function setPerspectiveOverlayDefaults(name) {
  const checked = name === 'truth'
  if (name !== 'candidate' && name !== 'truth') return
  for (const selector of ['#toggle-room-labels', '#toggle-fixtures']) {
    const input = document.querySelector(selector)
    input.checked = checked
    input.dispatchEvent(new Event('change'))
  }
}

function inspectAtEvent(event) {
  const bounds = canvas.getBoundingClientRect()
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
  raycaster.setFromCamera(pointer, activeCamera)
  const hit = raycaster.intersectObjects(inspectable, false).find(({ object }) => {
    let current = object
    while (current) {
      if (!current.visible) return false
      current = current.parent
    }
    return true
  })?.object ?? null

  updateSelection(hit)
}

canvas.addEventListener('pointermove', inspectAtEvent)
canvas.addEventListener('click', inspectAtEvent)

document.querySelector('#scene-summary').textContent = `${data.slabs.length} slabs · ${data.walls.length} wall extrusions · ${data.openings.length} registered openings · ${data.blockers.filter((item) => item.scope === 'primary').length} primary blockers`
document.querySelector('#fingerprint').textContent = `GeometryScene fingerprint ${data.fingerprint}`
const candidateReadout = document.querySelector('#candidate-camera')

function vectorText(vector) {
  return `[${vector.x.toFixed(2)}, ${vector.y.toFixed(2)}, ${vector.z.toFixed(2)}]`
}

function updateCandidateReadout(candidate) {
  candidateReadout.textContent = `Accepted Camera v2 · derived viewport eye ${vectorText(candidate.eye)} · target ${vectorText(candidate.target)} · derived distance ${candidate.distance.toFixed(2)} GU`
}

function setView(name) {
  kitchenWallSkin.visible = name !== 'truth'
  activeView = name
  const preset = presets[name]
  activeCamera = name === 'truth' ? truthCamera : perspectiveCamera
  if (name !== 'truth') setPerspectivePresentationReflection(name === 'candidate')
  if (name === 'truth') {
    const presentation = preset.presentationTransform
    world.scale.set(presentation.scale.x, presentation.scale.y, presentation.scale.z)
    world.position.set(0, 2 * presentation.pivotY, 0)
  } else {
    world.scale.set(1, 1, 1)
    world.position.set(0, 0, 0)
  }
  controls.object = activeCamera
  controls.enableRotate = name !== 'truth'
  activeCamera.position.set(preset.eye.x, preset.eye.y, preset.eye.z)
  controls.target.set(preset.target.x, preset.target.y, preset.target.z)
  activeCamera.lookAt(controls.target)
  controls.update()
  controls.saveState()
  setPerspectiveOverlayDefaults(name)
  document.querySelectorAll('[data-view]').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === name)
  })
}

document.querySelector('#perspective-candidate').addEventListener('click', () => setView('candidate'))
document.querySelector('#top-down-truth').addEventListener('click', () => setView('truth'))
document.querySelector('#legacy-camera').addEventListener('click', () => setView('legacy'))
document.querySelector('#reset-camera').addEventListener('click', () => setView(activeView))

function resize() {
  const { clientWidth: width, clientHeight: height } = canvas
  renderer.setSize(width, height, false)
  const aspect = width / height
  perspectiveCamera.aspect = aspect
  // Three expects a vertical FOV; recomputing it preserves the accepted 45°
  // horizontal field of view for every inspector viewport.
  perspectiveCamera.fov = horizontalFovToVertical(data.camera.horizontal_fov_degrees, aspect)
  perspectiveCamera.updateProjectionMatrix()
  const candidate = perspectiveCandidate(data.bounds, aspect, data.camera)
  const truth = topDownTruthView(data.bounds, aspect)
  truthCamera.up.set(truth.cameraUp.x, truth.cameraUp.y, truth.cameraUp.z)
  truthCamera.left = -truth.halfWidth
  truthCamera.right = truth.halfWidth
  truthCamera.top = truth.halfHeight
  truthCamera.bottom = -truth.halfHeight
  truthCamera.updateProjectionMatrix()
  presets = {
    candidate,
    truth,
    legacy: {
      eye: Object.fromEntries(['x', 'y', 'z'].map((axis, index) => [axis, data.camera.legacyComparison.eye_gu[index]])),
      target: Object.fromEntries(['x', 'y', 'z'].map((axis, index) => [axis, data.camera.legacyComparison.target_gu[index]])),
    },
  }
  controls.minDistance = Math.max(10, candidate.distance * 0.2)
  controls.maxDistance = candidate.distance * 3
  updateCandidateReadout(candidate)
  setView(activeView)
}

window.addEventListener('resize', resize)
resize()

renderer.setAnimationLoop(() => {
  controls.update()
  renderer.render(scene, activeCamera)
})
