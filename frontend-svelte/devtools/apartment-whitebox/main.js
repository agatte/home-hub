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
  selection.textContent = object ? metadataText(object.userData.inspection) : 'Hover or click a wall/opening for its source metadata.'
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
if (onBedroomFace) diffuseColor.a = bedroomOpacity;`)
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

for (const room of data.rooms) {
  const label = textSprite(room.label, '#182f35')
  label.position.set(room.position.x, room.position.y, 14)
  overlayGroups.rooms.add(label)
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

function bindToggle(selector, group) {
  const input = document.querySelector(selector)
  group.visible = input.checked
  input.addEventListener('change', () => { group.visible = input.checked })
}

bindToggle('#toggle-room-labels', overlayGroups.rooms)
bindToggle('#toggle-fixtures', overlayGroups.fixtures)
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
  updateSelection(raycaster.intersectObjects(inspectable, false)[0]?.object ?? null)
}

canvas.addEventListener('pointermove', inspectAtEvent)
canvas.addEventListener('click', inspectAtEvent)

document.querySelector('#scene-summary').textContent = `${data.slabs.length} slabs · ${data.walls.length} wall extrusions · ${data.openings.length} registered openings`
document.querySelector('#fingerprint').textContent = `GeometryScene fingerprint ${data.fingerprint}`
const candidateReadout = document.querySelector('#candidate-camera')

function vectorText(vector) {
  return `[${vector.x.toFixed(2)}, ${vector.y.toFixed(2)}, ${vector.z.toFixed(2)}]`
}

function updateCandidateReadout(candidate) {
  candidateReadout.textContent = `Accepted Camera v2 · derived viewport eye ${vectorText(candidate.eye)} · target ${vectorText(candidate.target)} · derived distance ${candidate.distance.toFixed(2)} GU`
}

function setView(name) {
  activeView = name
  const preset = presets[name]
  activeCamera = name === 'truth' ? truthCamera : perspectiveCamera
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
