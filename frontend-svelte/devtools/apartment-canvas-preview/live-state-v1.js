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
    emissiveIntensity: 3.2,
    roughness: 0.34,
  }),
  lampHalo: new THREE.MeshBasicMaterial({
    color: PREVIEW_LAMP_COLOR,
    transparent: true,
    opacity: 0.15,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  }),
  monitorScreen: new THREE.MeshStandardMaterial({
    color: 0x182326,
    emissive: PREVIEW_MONITOR_COLOR,
    emissiveIntensity: 1.75,
    roughness: 0.34,
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

function softPoolMaterial(opacity) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      poolColor: { value: new THREE.Color(PREVIEW_LAMP_COLOR) },
      poolOpacity: { value: opacity },
    },
    vertexShader: `
      varying vec2 poolUv;
      void main() {
        poolUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 poolUv;
      uniform vec3 poolColor;
      uniform float poolOpacity;
      void main() {
        float radius = distance(poolUv, vec2(0.5)) * 2.0;
        float falloff = pow(max(0.0, 1.0 - radius), 2.2);
        gl_FragColor = vec4(poolColor, falloff * poolOpacity);
      }
    `,
  })
}

function addSoftPool(group, x, y, z, width, height, opacity) {
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    softPoolMaterial(opacity),
  )
  mesh.position.set(x, y, z)
  group.add(mesh)
}

function addLampState(group, id, enabled) {
  if (!enabled) return
  const f = rawObjectRect(id)
  if (!f) return

  const cx = f.x + f.w / 2
  const cy = f.y + f.h / 2
  const sourceRadius = Math.max(2.8, Math.min(f.w, f.h) * 0.20)
  const sourceZ = 154

  const source = new THREE.Mesh(
    new THREE.SphereGeometry(sourceRadius, 18, 12),
    materials.lampSource,
  )
  source.position.set(cx, cy, sourceZ)
  group.add(source)

  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(sourceRadius * 2.7, 18, 12),
    materials.lampHalo,
  )
  halo.position.copy(source.position)
  group.add(halo)

  const light = new THREE.PointLight(PREVIEW_LAMP_COLOR, 2300, 390, 1.8)
  light.position.set(cx, cy, sourceZ - 5)
  light.castShadow = true
  light.shadow.mapSize.set(512, 512)
  light.shadow.bias = -0.001
  group.add(light)

  // Soft pools ensure the local physical consequence survives the neutral
  // studio rig at the accepted hero camera without painting the whole room.
  addSoftPool(group, cx, cy, 3.2, 205, 175, 0.10)
  addSoftPool(group, cx, cy, 104.7, 92, 78, 0.20)
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

  const glow = new THREE.PointLight(PREVIEW_MONITOR_COLOR, 320, 210, 1.65)
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
