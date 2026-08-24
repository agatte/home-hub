import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import {
  adaptGeometryScene,
  horizontalFovToVertical,
  perspectiveCandidate,
} from '../apartment-whitebox/adapter.js'
import './styles.css'

const EXPECTED_FINGERPRINT = 'ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43'
const debugEnabled = new URLSearchParams(window.location.search).has('debug')
const data = adaptGeometryScene(geometryScene)

if (data.fingerprint !== EXPECTED_FINGERPRINT) {
  throw new Error(`Apartment Canvas preview expected GeometryScene ${EXPECTED_FINGERPRINT}, received ${data.fingerprint}`)
}

// Accepted measured inspector verticals are presentation inputs for the base
// render. They intentionally do not mutate GeometryScene XY authority.
const ceilingTopZ = 364.43
const originalWallTopZ = Math.max(...data.walls.map((wall) => wall.zMax))
const measuredApertureZ = new Map([
  ['bedroom_window_left', { min: 81.36, max: 311.88 }],
  ['bedroom_window_right', { min: 81.36, max: 311.88 }],
  ['living_window_left', { min: 81.36, max: 311.88 }],
  ['living_window_right', { min: 81.36, max: 311.88 }],
  ['balcony_door', { min: 0, max: 267.81 }],
  ['bedroom_door', { min: 0, max: 271.20 }],
  ['bathroom_door', { min: 0, max: 271.20 }],
  ['laundry_door', { min: 0, max: 271.20 }],
  ['water_heater_door', { min: 0, max: 271.20 }],
  ['front_door', { min: 0, max: 271.20 }],
  ['closet_opening', { min: 0, max: 271.20 }],
])

for (const wall of data.walls) {
  if (Math.abs(wall.zMax - originalWallTopZ) < 0.001) wall.zMax = ceilingTopZ
}
for (const opening of data.openings) {
  const measured = measuredApertureZ.get(opening.sourceApertureId)
  if (!measured) continue
  opening.void = { ...measured }
  if (!opening.closureFootprint) continue
  opening.solidRanges = opening.kind === 'window'
    ? [
        { min: 0, max: measured.min },
        { min: measured.max, max: ceilingTopZ },
      ]
    : [{ min: measured.max, max: ceilingTopZ }]
}
data.bounds.maxZ = ceilingTopZ

const canvas = document.querySelector('#apartment-canvas')
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false })
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
renderer.setClearColor(0x111514, 1)
renderer.outputColorSpace = THREE.SRGBColorSpace
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.toneMappingExposure = 1.08
renderer.shadowMap.enabled = true
renderer.shadowMap.type = THREE.PCFSoftShadowMap

const scene = new THREE.Scene()
scene.background = new THREE.Color(0x111514)
scene.fog = new THREE.FogExp2(0x111514, 0.00022)
const world = new THREE.Group()
scene.add(world)

const camera = new THREE.PerspectiveCamera(40, 1, 1, 10000)
camera.up.set(0, 0, 1)
const controls = new OrbitControls(camera, renderer.domElement)
controls.enabled = debugEnabled
controls.enableDamping = true
controls.dampingFactor = 0.08
controls.enablePan = debugEnabled
controls.enableZoom = debugEnabled

const hemisphere = new THREE.HemisphereLight(0xf8f2e8, 0x4a514d, 2.0)
scene.add(hemisphere)

const key = new THREE.DirectionalLight(0xfff3e4, 3.0)
key.position.set(220, -620, 1050)
key.castShadow = true
key.shadow.mapSize.set(2048, 2048)
key.shadow.camera.near = 100
key.shadow.camera.far = 2600
key.shadow.camera.left = -900
key.shadow.camera.right = 900
key.shadow.camera.top = 900
key.shadow.camera.bottom = -900
key.shadow.bias = -0.00025
scene.add(key)

const fill = new THREE.DirectionalLight(0xdce8e6, 1.15)
fill.position.set(1180, 1200, 620)
scene.add(fill)

const stage = new THREE.Mesh(
  new THREE.PlaneGeometry(2300, 2100),
  new THREE.MeshStandardMaterial({ color: 0x202725, roughness: 1, metalness: 0 }),
)
stage.position.set(500, 640, -8)
stage.receiveShadow = true
world.add(stage)

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

const cutawayCandidate = data.presentation.cutawayCandidates.find((candidate) => candidate.id === 'accepted_north')
if (!cutawayCandidate?.available) throw new Error('Accepted north cutaway is unavailable')
const cutawayUniforms = {
  cutawayLip: { value: data.presentation.cutaway.lipHeightGu },
  cutawayCount: { value: cutawayCandidate.targets.length },
  cutawayMinX0: { value: 0 }, cutawayMaxX0: { value: 0 }, cutawayMinY0: { value: 0 }, cutawayMaxY0: { value: 0 },
  cutawayMinX1: { value: 0 }, cutawayMaxX1: { value: 0 }, cutawayMinY1: { value: 0 }, cutawayMaxY1: { value: 0 },
}
for (const [index, target] of cutawayCandidate.targets.entries()) {
  cutawayUniforms[`cutawayMinX${index}`].value = target.bounds.minX
  cutawayUniforms[`cutawayMaxX${index}`].value = target.bounds.maxX
  cutawayUniforms[`cutawayMinY${index}`].value = target.bounds.minY
  cutawayUniforms[`cutawayMaxY${index}`].value = target.bounds.maxY
}

function boundsUniforms(bounds) {
  return {
    minX: { value: bounds.minX }, maxX: { value: bounds.maxX },
    minY: { value: bounds.minY }, maxY: { value: bounds.maxY },
  }
}

function makeWallMaterial() {
  const material = new THREE.MeshStandardMaterial({
    color: 0xd8d1c5,
    roughness: 0.92,
    metalness: 0,
    transparent: true,
    depthWrite: true,
    side: THREE.DoubleSide,
  })
  const bedroomUniforms = boundsUniforms(data.presentation.bedroom.faceBounds)
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, {
      ...cutawayUniforms,
      bedroomBase: { value: data.presentation.bedroom.solidBaseHeightGu },
      bedroomOpacity: { value: data.presentation.bedroom.upperOpacity },
      ...Object.fromEntries(Object.entries(bedroomUniforms).map(([keyName, value]) => [
        `bedroom${keyName[0].toUpperCase()}${keyName.slice(1)}`,
        value,
      ])),
    })
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 apartmentWorldPosition;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\napartmentWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 apartmentWorldPosition;
uniform float cutawayLip;
uniform int cutawayCount;
uniform float cutawayMinX0; uniform float cutawayMaxX0; uniform float cutawayMinY0; uniform float cutawayMaxY0;
uniform float cutawayMinX1; uniform float cutawayMaxX1; uniform float cutawayMinY1; uniform float cutawayMaxY1;
uniform float bedroomBase; uniform float bedroomOpacity;
uniform float bedroomMinX; uniform float bedroomMaxX; uniform float bedroomMinY; uniform float bedroomMaxY;`)
      .replace('#include <color_fragment>', `#include <color_fragment>
bool inCutaway = cutawayCount > 0 && apartmentWorldPosition.x >= cutawayMinX0 && apartmentWorldPosition.x <= cutawayMaxX0
  && apartmentWorldPosition.y >= cutawayMinY0 && apartmentWorldPosition.y <= cutawayMaxY0;
inCutaway = inCutaway || (cutawayCount > 1 && apartmentWorldPosition.x >= cutawayMinX1 && apartmentWorldPosition.x <= cutawayMaxX1
  && apartmentWorldPosition.y >= cutawayMinY1 && apartmentWorldPosition.y <= cutawayMaxY1);
if (inCutaway && apartmentWorldPosition.z > cutawayLip) discard;
bool onBedroomFace = apartmentWorldPosition.x >= bedroomMinX && apartmentWorldPosition.x <= bedroomMaxX
  && abs(apartmentWorldPosition.y - bedroomMinY) < 0.001 && apartmentWorldPosition.z > bedroomBase;
if (onBedroomFace) diffuseColor.a = bedroomOpacity;
bool inEntryTallCabinetFalseWall = apartmentWorldPosition.x >= 359.64 && apartmentWorldPosition.x <= 444.39
  && apartmentWorldPosition.y >= 1041.315 && apartmentWorldPosition.y <= 1085.385;
if (inEntryTallCabinetFalseWall) discard;`)
  }
  return material
}

const wallMaterial = makeWallMaterial()
const closureMaterial = new THREE.MeshStandardMaterial({ color: 0xd8d1c5, roughness: 0.92, metalness: 0, side: THREE.DoubleSide })
const apartmentFloorMaterial = new THREE.MeshStandardMaterial({ color: 0x8f887c, roughness: 0.98, metalness: 0 })
const balconyFloorMaterial = new THREE.MeshStandardMaterial({ color: 0x686f6d, roughness: 0.96, metalness: 0 })
const glassMaterial = new THREE.MeshPhysicalMaterial({
  color: 0x9fb1b2,
  roughness: 0.12,
  metalness: 0,
  transparent: true,
  opacity: 0.23,
  transmission: 0.12,
  side: THREE.DoubleSide,
  depthWrite: false,
})

for (const slab of data.slabs) {
  const mesh = new THREE.Mesh(
    extrusionFromRings(slab.ring, [], slab.zMin, slab.zMax),
    slab.kind === 'balcony_floor_slab' ? balconyFloorMaterial : apartmentFloorMaterial,
  )
  mesh.receiveShadow = true
  world.add(mesh)
}

for (const wall of data.walls) {
  const geometry = extrusionFromRings(wall.outer, wall.holes, wall.zMin, wall.zMax)
  const mesh = new THREE.Mesh(geometry, wallMaterial)
  mesh.castShadow = true
  mesh.receiveShadow = true
  world.add(mesh)
}

// Presentation-only skin retained from the accepted whitebox to suppress tiny
// east-kitchen contour fins without altering GeometryScene coordinates.
const kitchenWallSkin = new THREE.Mesh(
  extrusionFromRings([
    { x: 980.50, y: 755.90 }, { x: 981.30, y: 755.90 },
    { x: 981.30, y: 1230.27 }, { x: 980.50, y: 1230.27 },
  ], [], 0, ceilingTopZ),
  wallMaterial,
)
kitchenWallSkin.castShadow = true
kitchenWallSkin.receiveShadow = true
world.add(kitchenWallSkin)

for (const opening of data.openings) {
  if (opening.closureFootprint) {
    for (const range of opening.solidRanges) {
      const closure = new THREE.Mesh(
        extrusionFromRings(opening.closureFootprint, [], range.min, range.max),
        closureMaterial,
      )
      closure.castShadow = true
      closure.receiveShadow = true
      world.add(closure)
    }
  }

  const isWindow = opening.kind === 'window'
  const isBalconyDoor = opening.sourceApertureId === 'balcony_door'
  if (!opening.closureFootprint || (!isWindow && !isBalconyDoor)) continue

  const glassBottom = isBalconyDoor ? 40.68 : opening.void.min + 5
  const glassTop = isBalconyDoor ? 252.56 : opening.void.max - 5
  if (glassTop <= glassBottom) continue
  const pane = new THREE.Mesh(
    extrusionFromRings(opening.closureFootprint, [], glassBottom, glassTop),
    glassMaterial,
  )
  pane.receiveShadow = true
  world.add(pane)
}

function applyAcceptedProjectionReflection() {
  camera.updateProjectionMatrix()
  camera.projectionMatrix.elements[0] *= -1
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert()
}

const debugPanel = document.querySelector('#debug-panel')
if (debugEnabled) debugPanel.hidden = false

function resize() {
  const width = Math.max(1, canvas.clientWidth)
  const height = Math.max(1, canvas.clientHeight)
  const aspect = width / height
  renderer.setSize(width, height, false)
  camera.aspect = aspect
  camera.fov = horizontalFovToVertical(data.camera.horizontal_fov_degrees, aspect)
  const candidate = perspectiveCandidate(data.bounds, aspect, data.camera)
  camera.position.set(candidate.eye.x, candidate.eye.y, candidate.eye.z)
  controls.target.set(candidate.target.x, candidate.target.y, candidate.target.z)
  camera.lookAt(controls.target)
  applyAcceptedProjectionReflection()
  controls.minDistance = Math.max(10, candidate.distance * 0.2)
  controls.maxDistance = candidate.distance * 3
  controls.update()

  if (debugEnabled) {
    debugPanel.textContent = [
      'Apartment Canvas · architectural shell',
      `GeometryScene ${data.fingerprint}`,
      `eye [${candidate.eye.x.toFixed(2)}, ${candidate.eye.y.toFixed(2)}, ${candidate.eye.z.toFixed(2)}]`,
      `target [${candidate.target.x.toFixed(2)}, ${candidate.target.y.toFixed(2)}, ${candidate.target.z.toFixed(2)}]`,
      `distance ${candidate.distance.toFixed(2)} GU`,
    ].join('\n')
  }
}

new ResizeObserver(resize).observe(canvas)
resize()

renderer.setAnimationLoop(() => {
  if (debugEnabled) controls.update()
  renderer.render(scene, camera)
})
