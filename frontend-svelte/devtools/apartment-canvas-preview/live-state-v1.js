import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { parseRational } from '../apartment-whitebox/adapter.js'

// Preview-only visualization fixtures. These values are deliberately local to
// the synthetic review harness and are NOT production Hue colors/brightness.
const PREVIEW_LAMP_COLOR = 0xffd6a3
const PREVIEW_MONITOR_COLOR = 0x9fc6d2

const materials = Object.freeze({
  lampSource: new THREE.MeshStandardMaterial({
    color: 0xffe6c5,
    emissive: PREVIEW_LAMP_COLOR,
    emissiveIntensity: 2.4,
    roughness: 0.42,
  }),
  monitorScreen: new THREE.MeshStandardMaterial({
    color: 0x182326,
    emissive: PREVIEW_MONITOR_COLOR,
    emissiveIntensity: 1.45,
    roughness: 0.38,
    side: THREE.DoubleSide,
  }),
})

function rawObjectRect(id) {
  const item = geometryScene.inspection_annotations.objects.find((object) => object.id === id)
  if (!item?.rect_gu) return null
  return Object.fromEntries(Object.entries(item.rect_gu).map(([key, token]) => [key, parseRational(token)]))
}

function blockerFootprint(data, id) {
  const blocker = data.blockers.find((item) => item.id === id)
  return blocker ? blocker.renderFootprint ?? blocker.sourceFootprint : null
}

function addLampState(group, id, enabled) {
  if (!enabled) return
  const f = rawObjectRect(id)
  if (!f) return

  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const sourceRadius = Math.max(2.6, Math.min(f.w, f.h) * 0.19)
  const sourceZ = 154

  const source = new THREE.Mesh(
    new THREE.SphereGeometry(sourceRadius, 18, 12),
    materials.lampSource,
  )
  source.position.set(cx, cy, sourceZ)
  group.add(source)

  const light = new THREE.PointLight(PREVIEW_LAMP_COLOR, 520, 255, 1.45)
  light.position.set(cx, cy, sourceZ - 4)
  group.add(light)
}

function addMonitorState(group, data, enabled) {
  if (!enabled) return
  const f = blockerFootprint(data, 'bedroom.monitor')
  if (!f) return

  const width = f.w * 0.84
  const height = 39
  const geometry = new THREE.PlaneGeometry(width, height)
  geometry.rotateX(Math.PI / 2)

  const screen = new THREE.Mesh(geometry, materials.monitorScreen)
  screen.position.set(
    f.x + f.w / 2,
    f.y + f.h * 0.24,
    128,
  )
  group.add(screen)

  const glow = new THREE.PointLight(PREVIEW_MONITOR_COLOR, 130, 145, 1.55)
  glow.position.set(f.x + f.w / 2, f.y + f.h * 0.36, 126)
  group.add(glow)
}

export function addApartmentLiveStateV1(world, data, state) {
  const group = new THREE.Group()
  group.name = `apartment-live-state:${state.id}`

  addLampState(group, 'bedroom.lamp_l2', state.lamps.bedroomL2)
  addLampState(group, 'bedroom.lamp_l5', state.lamps.bedroomL5)
  addMonitorState(group, data, state.displays.monitor)

  world.add(group)
  return group
}
