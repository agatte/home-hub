import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import {
  adaptGeometryScene,
  horizontalFovToVertical,
  perspectiveCandidate,
} from '../apartment-whitebox/adapter.js'
import { bedroomWindowWallClosureFootprint } from './bedroom-window-wall-v1.js'
import './styles.css'

const EXPECTED_FINGERPRINT = 'ba9270ddd772aa859dca2e155e14a54c8d1eccb3daeb869e6301780bbdd4cf43'
// Camera v2 remains the authority for the viewpoint family, target, 45-degree
// horizontal FOV, reflection, and responsive corner-containment solve. This is
// the static preview's only presentation allowance: a smaller, still-positive
// desktop breathing room so the contained apartment reads as the hero rather
// than a distant object. It does not mutate the accepted policy artifact.
const PRESENTATION_FIT_MARGIN = 1.06
const debugEnabled = new URLSearchParams(window.location.search).has('debug')
const data = adaptGeometryScene(geometryScene)

if (data.fingerprint !== EXPECTED_FINGERPRINT) {
  throw new Error(`Apartment Canvas preview expected GeometryScene ${EXPECTED_FINGERPRINT}, received ${data.fingerprint}`)
}

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
renderer.setClearColor(0x111816, 1)
renderer.outputColorSpace = THREE.SRGBColorSpace
renderer.toneMapping = THREE.ACESFilmicToneMapping
renderer.toneMappingExposure = 1.32
renderer.shadowMap.enabled = true
renderer.shadowMap.type = THREE.PCFSoftShadowMap

const scene = new THREE.Scene()
scene.background = new THREE.Color(0x111816)
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

scene.add(new THREE.AmbientLight(0xfffbf2, 0.72))
scene.add(new THREE.HemisphereLight(0xfff6e8, 0x35413d, 2.35))

const key = new THREE.DirectionalLight(0xfff0d9, 4.25)
key.position.set(70, -720, 1120)
key.castShadow = true
key.shadow.mapSize.set(2048, 2048)
key.shadow.camera.near = 80
key.shadow.camera.far = 2800
key.shadow.camera.left = -950
key.shadow.camera.right = 950
key.shadow.camera.top = 950
key.shadow.camera.bottom = -950
key.shadow.bias = -0.00015
key.shadow.normalBias = 1.2
scene.add(key)

const fill = new THREE.DirectionalLight(0xdbe9e7, 1.7)
fill.position.set(1250, 1050, 720)
scene.add(fill)

const rim = new THREE.DirectionalLight(0xc8d7d2, 0.72)
rim.position.set(-900, 1000, 540)
scene.add(rim)

const stage = new THREE.Mesh(
  new THREE.PlaneGeometry(2400, 2200),
  new THREE.MeshStandardMaterial({ color: 0x26302c, roughness: 0.98, metalness: 0 }),
)
stage.position.set(500, 640, -18)
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

function rectangleRing(bounds) {
  return [
    { x: bounds.minX, y: bounds.minY },
    { x: bounds.maxX, y: bounds.minY },
    { x: bounds.maxX, y: bounds.maxY },
    { x: bounds.minX, y: bounds.maxY },
  ]
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
    color: 0xe5ddd1,
    roughness: 0.86,
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
      bedroomOpacity: { value: Math.max(0.42, data.presentation.bedroom.upperOpacity) },
      ...Object.fromEntries(Object.entries(bedroomUniforms).map(([keyName, value]) => [
        `bedroom${keyName[0].toUpperCase()}${keyName.slice(1)}`,
        value,
      ])),
    })
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 apartmentWorldPosition;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\napartmentWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 apartmentWorldPosition;\nuniform float cutawayLip;\nuniform int cutawayCount;\nuniform float cutawayMinX0; uniform float cutawayMaxX0; uniform float cutawayMinY0; uniform float cutawayMaxY0;\nuniform float cutawayMinX1; uniform float cutawayMaxX1; uniform float cutawayMinY1; uniform float cutawayMaxY1;\nuniform float bedroomBase; uniform float bedroomOpacity;\nuniform float bedroomMinX; uniform float bedroomMaxX; uniform float bedroomMinY; uniform float bedroomMaxY;`)
      .replace('#include <color_fragment>', `#include <color_fragment>\nbool inCutaway = cutawayCount > 0 && apartmentWorldPosition.x >= cutawayMinX0 && apartmentWorldPosition.x <= cutawayMaxX0\n  && apartmentWorldPosition.y >= cutawayMinY0 && apartmentWorldPosition.y <= cutawayMaxY0;\ninCutaway = inCutaway || (cutawayCount > 1 && apartmentWorldPosition.x >= cutawayMinX1 && apartmentWorldPosition.x <= cutawayMaxX1\n  && apartmentWorldPosition.y >= cutawayMinY1 && apartmentWorldPosition.y <= cutawayMaxY1);\nif (inCutaway && apartmentWorldPosition.z > cutawayLip) discard;\nbool onBedroomFace = apartmentWorldPosition.x >= bedroomMinX && apartmentWorldPosition.x <= bedroomMaxX\n  && abs(apartmentWorldPosition.y - bedroomMinY) < 0.001 && apartmentWorldPosition.z > bedroomBase;\nif (onBedroomFace) diffuseColor.a = bedroomOpacity;\nbool inEntryTallCabinetFalseWall = apartmentWorldPosition.x >= 359.64 && apartmentWorldPosition.x <= 444.39\n  && apartmentWorldPosition.y >= 1041.315 && apartmentWorldPosition.y <= 1085.385;\nif (inEntryTallCabinetFalseWall) discard;`)
  }
  return material
}

function makeApartmentFloorMaterial() {
  const material = new THREE.MeshStandardMaterial({
    color: 0xbca98d,
    roughness: 0.9,
    metalness: 0,
  })
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 apartmentFloorWorldPosition;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\napartmentFloorWorldPosition = (modelMatrix * vec4(transformed, 1.0)).xyz;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec3 apartmentFloorWorldPosition;')
      .replace('#include <color_fragment>', `#include <color_fragment>\nfloat board = floor(apartmentFloorWorldPosition.x / 48.0);\nfloat row = floor(apartmentFloorWorldPosition.y / 18.0);\nfloat tone = mod(board + row * 0.5, 2.0) * 0.018;\nfloat seam = smoothstep(0.0, 1.8, mod(apartmentFloorWorldPosition.y, 18.0));\nseam *= 1.0 - smoothstep(1.8, 3.6, mod(apartmentFloorWorldPosition.y, 18.0));\ndiffuseColor.rgb *= 0.985 + tone - seam * 0.035;`)
  }
  return material
}

const wallMaterial = makeWallMaterial()
const closureMaterial = new THREE.MeshStandardMaterial({ color: 0xe5ddd1, roughness: 0.86, metalness: 0, side: THREE.DoubleSide })
const apartmentFloorMaterial = makeApartmentFloorMaterial()
const balconyFloorMaterial = new THREE.MeshStandardMaterial({ color: 0x747c77, roughness: 0.98, metalness: 0 })
const plinthMaterial = new THREE.MeshStandardMaterial({ color: 0x303735, roughness: 0.96, metalness: 0 })
const cutCapMaterial = new THREE.MeshStandardMaterial({ color: 0x766d62, roughness: 0.84, metalness: 0 })
const frameMaterial = new THREE.MeshStandardMaterial({ color: 0x626b68, roughness: 0.72, metalness: 0.08 })
const glassMaterial = new THREE.MeshPhysicalMaterial({
  color: 0xb3c9c7,
  roughness: 0.08,
  metalness: 0,
  transparent: true,
  opacity: 0.2,
  transmission: 0.32,
  clearcoat: 0.18,
  clearcoatRoughness: 0.18,
  side: THREE.DoubleSide,
  depthWrite: false,
})

for (const slab of data.slabs) {
  const isBalcony = slab.kind === 'balcony_floor_slab'
  const plinth = new THREE.Mesh(
    extrusionFromRings(slab.ring, [], slab.zMin - 10, slab.zMin - 1.2),
    plinthMaterial,
  )
  plinth.castShadow = true
  plinth.receiveShadow = true
  world.add(plinth)

  const mesh = new THREE.Mesh(
    extrusionFromRings(slab.ring, [], slab.zMin, slab.zMax),
    isBalcony ? balconyFloorMaterial : apartmentFloorMaterial,
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

for (const target of cutawayCandidate.targets) {
  const bounds = { ...target.bounds }
  if (Math.abs(bounds.maxX - bounds.minX) < 1) {
    bounds.minX -= 2
    bounds.maxX += 2
  }
  if (Math.abs(bounds.maxY - bounds.minY) < 1) {
    bounds.minY -= 2
    bounds.maxY += 2
  }
  const cap = new THREE.Mesh(
    extrusionFromRings(rectangleRing(bounds), [], data.presentation.cutaway.lipHeightGu - 0.2, data.presentation.cutaway.lipHeightGu + 3.6),
    cutCapMaterial,
  )
  cap.castShadow = true
  cap.receiveShadow = true
  world.add(cap)
}

function cylinderBetween(a, b, radius, material) {
  const start = new THREE.Vector3(a.x, a.y, a.z)
  const end = new THREE.Vector3(b.x, b.y, b.z)
  const delta = end.clone().sub(start)
  const length = delta.length()
  const geometry = new THREE.CylinderGeometry(radius, radius, length, 10)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.position.copy(start).add(end).multiplyScalar(0.5)
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.clone().normalize())
  mesh.castShadow = true
  return mesh
}

for (const opening of data.openings) {
  if (opening.closureFootprint) {
    const closureFootprint = bedroomWindowWallClosureFootprint(opening)
    for (const range of opening.solidRanges) {
      const closure = new THREE.Mesh(
        extrusionFromRings(closureFootprint, [], range.min, range.max),
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

  const glassBottom = isBalconyDoor ? 40.68 : opening.void.min + 6
  const glassTop = isBalconyDoor ? 252.56 : opening.void.max - 6
  if (glassTop <= glassBottom) continue

  const pane = new THREE.Mesh(
    extrusionFromRings(opening.closureFootprint, [], glassBottom, glassTop),
    glassMaterial,
  )
  world.add(pane)

  const [first, last] = opening.segment
  const frameRadius = isBalconyDoor ? 3.4 : 2.8
  world.add(cylinderBetween(
    { x: first.x, y: first.y, z: glassBottom },
    { x: last.x, y: last.y, z: glassBottom },
    frameRadius,
    frameMaterial,
  ))
  world.add(cylinderBetween(
    { x: first.x, y: first.y, z: glassTop },
    { x: last.x, y: last.y, z: glassTop },
    frameRadius,
    frameMaterial,
  ))
  world.add(cylinderBetween(
    { x: first.x, y: first.y, z: glassBottom },
    { x: first.x, y: first.y, z: glassTop },
    frameRadius,
    frameMaterial,
  ))
  world.add(cylinderBetween(
    { x: last.x, y: last.y, z: glassBottom },
    { x: last.x, y: last.y, z: glassTop },
    frameRadius,
    frameMaterial,
  ))
}

function applyAcceptedProjectionReflection() {
  camera.updateProjectionMatrix()
  camera.projectionMatrix.elements[0] *= -1
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert()
}

function presentationCameraPolicy(cameraPolicy) {
  return {
    ...cameraPolicy,
    fit_policy: {
      ...cameraPolicy.fit_policy,
      margin: PRESENTATION_FIT_MARGIN,
    },
  }
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
  const candidate = perspectiveCandidate(data.bounds, aspect, presentationCameraPolicy(data.camera))
  camera.position.set(candidate.eye.x, candidate.eye.y, candidate.eye.z)
  controls.target.set(candidate.target.x, candidate.target.y, candidate.target.z)
  camera.lookAt(controls.target)
  applyAcceptedProjectionReflection()
  controls.minDistance = Math.max(10, candidate.distance * 0.2)
  controls.maxDistance = candidate.distance * 3
  controls.update()

  if (debugEnabled) {
    debugPanel.textContent = [
      'Apartment Canvas · architectural shell v2',
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
