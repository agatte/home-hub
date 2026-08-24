import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene, perspectiveCandidate } from '../apartment-whitebox/adapter.js'
import { cameraPolicyForPose, resolveContextCameraPose } from './camera-poses.js'

const DURATION_MS = 2200
const HERO_HOLD_MS = 900
const ARC_HEIGHT_GU = 18

function ease(value) {
  const t = THREE.MathUtils.clamp(value, 0, 1)
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function footprint(data, id) {
  const blocker = data.blockers.find((item) => item.id === id)
  return blocker ? blocker.renderFootprint ?? blocker.sourceFootprint : null
}

function center(rect) {
  return { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2 }
}

function livingEndpoint(data, pose) {
  const tv = footprint(data, pose.tvId)
  const couch = footprint(data, pose.couchId)
  if (!tv || !couch) throw new Error('Living camera requires TV and couch footprints')

  const a = center(tv)
  const b = center(couch)
  const dx = b.x - a.x
  const dy = b.y - a.y
  const length = Math.hypot(dx, dy)
  const ux = dx / length
  const uy = dy / length

  return {
    eye: new THREE.Vector3(
      b.x + ux * pose.eyeBeyondCouchGu,
      b.y + uy * pose.eyeBeyondCouchGu,
      pose.eyeZGu,
    ),
    target: new THREE.Vector3(
      a.x + ux * pose.targetTowardCouchGu,
      a.y + uy * pose.targetTowardCouchGu,
      pose.targetZGu,
    ),
  }
}

function endpointFor(data, pose, camera) {
  if (pose.strategy === 'tv-couch-axis') return livingEndpoint(data, pose)

  const aspect = camera.aspect > 0 ? camera.aspect : 1
  const policy = cameraPolicyForPose(data.camera, pose)
  const candidate = perspectiveCandidate(data.bounds, aspect, policy)
  const target = new THREE.Vector3(candidate.target.x, candidate.target.y, candidate.target.z)
  const eye = new THREE.Vector3(candidate.eye.x, candidate.eye.y, candidate.eye.z)
  return {
    eye: target.clone().add(eye.sub(target).multiplyScalar(pose.distanceScale)),
    target,
  }
}

export function installContextCameraMotionPreview(stateId, search = window.location.search) {
  const pose = resolveContextCameraPose(stateId)
  const params = new URLSearchParams(String(search).replace(/^\?/, ''))
  if (pose.id === 'rest' || params.has('debug')) return () => {}

  const data = adaptGeometryScene(geometryScene)
  const forceMotion = params.get('motion') === 'force'
  const reducedMotion = !forceMotion
    && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  const originalLookAt = THREE.Object3D.prototype.lookAt

  let disposed = false
  let timer = null
  let frame = null
  let captured = false

  function animate(camera, baseTarget) {
    const endpoint = endpointFor(data, pose, camera)
    const fromEye = camera.position.clone()
    const fromTarget = baseTarget.clone()

    if (reducedMotion) {
      camera.position.copy(endpoint.eye)
      originalLookAt.call(camera, endpoint.target)
      return
    }

    const started = performance.now()
    const target = new THREE.Vector3()
    const tick = (now) => {
      if (disposed) return
      const linear = Math.min(1, (now - started) / DURATION_MS)
      const t = ease(linear)
      camera.position.lerpVectors(fromEye, endpoint.eye, t)
      camera.position.z += Math.sin(Math.PI * t) * ARC_HEIGHT_GU
      target.lerpVectors(fromTarget, endpoint.target, t)
      originalLookAt.call(camera, target)
      if (linear < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
  }

  THREE.Object3D.prototype.lookAt = function (...args) {
    const result = originalLookAt.apply(this, args)
    if (!captured && this?.isPerspectiveCamera) {
      captured = true
      const camera = this
      const [x, y, z] = data.camera.target_gu.map(Number)
      const baseTarget = new THREE.Vector3(x, y, z)
      THREE.Object3D.prototype.lookAt = originalLookAt
      requestAnimationFrame(() => requestAnimationFrame(() => {
        timer = setTimeout(() => animate(camera, baseTarget), HERO_HOLD_MS)
      }))
    }
    return result
  }

  return () => {
    disposed = true
    THREE.Object3D.prototype.lookAt = originalLookAt
    if (timer !== null) clearTimeout(timer)
    if (frame !== null) cancelAnimationFrame(frame)
  }
}
