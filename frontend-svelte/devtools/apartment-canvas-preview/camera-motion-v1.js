import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene, perspectiveCandidate } from '../apartment-whitebox/adapter.js'
import { cameraPolicyForPose, resolveContextCameraPose } from './camera-poses.js'

const MOTION_DURATION_MS = 1100
const MOTION_DELAY_MS = 180
const MOTION_ARC_HEIGHT_GU = 12

function smootherStep(value) {
  const t = THREE.MathUtils.clamp(value, 0, 1)
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function scaledEye(candidate, distanceScale) {
  const target = new THREE.Vector3(candidate.target.x, candidate.target.y, candidate.target.z)
  const eye = new THREE.Vector3(candidate.eye.x, candidate.eye.y, candidate.eye.z)
  return target.clone().add(eye.sub(target).multiplyScalar(distanceScale))
}

/**
 * Preview-only contextual camera experiment for #184.
 *
 * Camera v2 remains the Rest authority. This hook captures the actual preview
 * PerspectiveCamera during main-v2's initial lookAt(), restores Three's
 * prototype immediately, and then animates that concrete camera instance.
 * It intentionally avoids changing the accepted renderer while the behavior is
 * still under visual review.
 */
export function installContextCameraMotionPreview(stateId, search = window.location.search) {
  const pose = resolveContextCameraPose(stateId)
  const params = search instanceof URLSearchParams
    ? search
    : new URLSearchParams(String(search).replace(/^\?/, ''))
  const debug = params.has('debug')
  if (pose.id === 'rest' || debug) return () => {}

  const data = adaptGeometryScene(geometryScene)
  const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  const originalLookAt = THREE.Object3D.prototype.lookAt

  let disposed = false
  let capturedCamera = null
  let animationFrame = null
  let startTimer = null
  let hookInstalled = true

  function restoreLookAtHook() {
    if (!hookInstalled) return
    THREE.Object3D.prototype.lookAt = originalLookAt
    hookInstalled = false
  }

  function derivePose(camera) {
    const aspect = camera.aspect > 0 ? camera.aspect : 1
    const baseCandidate = perspectiveCandidate(data.bounds, aspect, data.camera)
    const contextualPolicy = cameraPolicyForPose(data.camera, pose)
    const contextualCandidate = perspectiveCandidate(data.bounds, aspect, contextualPolicy)

    return {
      fromEye: camera.position.clone(),
      fromTarget: new THREE.Vector3(
        baseCandidate.target.x,
        baseCandidate.target.y,
        baseCandidate.target.z,
      ),
      toEye: scaledEye(contextualCandidate, pose.distanceScale),
      toTarget: new THREE.Vector3(
        contextualCandidate.target.x,
        contextualCandidate.target.y,
        contextualCandidate.target.z,
      ),
    }
  }

  function applyLookAt(camera, target) {
    originalLookAt.call(camera, target)
  }

  function startMotion(camera) {
    if (disposed) return
    const { fromEye, fromTarget, toEye, toTarget } = derivePose(camera)

    if (prefersReducedMotion) {
      camera.position.copy(toEye)
      applyLookAt(camera, toTarget)
      return
    }

    const startedAt = performance.now()
    const target = new THREE.Vector3()

    const tick = (now) => {
      if (disposed) return
      const linear = Math.min(1, (now - startedAt) / MOTION_DURATION_MS)
      const eased = smootherStep(linear)

      camera.position.lerpVectors(fromEye, toEye, eased)
      camera.position.z += Math.sin(Math.PI * eased) * MOTION_ARC_HEIGHT_GU
      target.lerpVectors(fromTarget, toTarget, eased)
      applyLookAt(camera, target)

      if (linear < 1) {
        animationFrame = window.requestAnimationFrame(tick)
      } else {
        camera.position.copy(toEye)
        applyLookAt(camera, toTarget)
      }
    }

    animationFrame = window.requestAnimationFrame(tick)
  }

  THREE.Object3D.prototype.lookAt = function (...args) {
    const result = originalLookAt.apply(this, args)

    if (!capturedCamera && this?.isPerspectiveCamera) {
      capturedCamera = this
      // main-v2 still has controls.update() to run in this same resize call.
      // Restore Three immediately, then begin after the intended hero pause.
      restoreLookAtHook()
      startTimer = window.setTimeout(() => startMotion(capturedCamera), MOTION_DELAY_MS)
    }

    return result
  }

  return () => {
    disposed = true
    restoreLookAtHook()
    if (startTimer !== null) window.clearTimeout(startTimer)
    if (animationFrame !== null) window.cancelAnimationFrame(animationFrame)
  }
}
