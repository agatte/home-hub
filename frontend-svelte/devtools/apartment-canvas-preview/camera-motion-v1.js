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
 * Preview-only camera transition hook for #184.
 *
 * The accepted Camera v2 policy remains the Rest anchor. Context poses derive a
 * temporary candidate from that policy; they do not become geometry/camera
 * authority. This intentionally avoids changing main-v2 while the visual
 * behavior is still experimental.
 */
export function installContextCameraMotionPreview(stateId, search = window.location.search) {
  const pose = resolveContextCameraPose(stateId)
  const params = search instanceof URLSearchParams ? search : new URLSearchParams(String(search).replace(/^\?/, ''))
  const debug = params.has('debug')
  if (pose.id === 'rest' || debug) return () => {}

  const data = adaptGeometryScene(geometryScene)
  const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  const originalRender = THREE.WebGLRenderer.prototype.render

  let lastAspect = null
  let initialized = false
  let completed = false
  let startAt = 0
  let fromEye = null
  let fromTarget = null
  let toEye = null
  let toTarget = null

  function deriveTargets(camera) {
    const aspect = camera.aspect > 0 ? camera.aspect : 1
    const baseCandidate = perspectiveCandidate(data.bounds, aspect, data.camera)
    const contextualPolicy = cameraPolicyForPose(data.camera, pose)
    const contextualCandidate = perspectiveCandidate(data.bounds, aspect, contextualPolicy)

    fromEye = initialized
      ? camera.position.clone()
      : new THREE.Vector3(baseCandidate.eye.x, baseCandidate.eye.y, baseCandidate.eye.z)
    fromTarget = initialized
      ? fromTarget?.clone() ?? new THREE.Vector3(baseCandidate.target.x, baseCandidate.target.y, baseCandidate.target.z)
      : new THREE.Vector3(baseCandidate.target.x, baseCandidate.target.y, baseCandidate.target.z)
    toEye = scaledEye(contextualCandidate, pose.distanceScale)
    toTarget = new THREE.Vector3(
      contextualCandidate.target.x,
      contextualCandidate.target.y,
      contextualCandidate.target.z,
    )
    lastAspect = aspect
  }

  THREE.WebGLRenderer.prototype.render = function (scene, camera) {
    if (camera?.isPerspectiveCamera) {
      const aspectChanged = lastAspect !== null && Math.abs(camera.aspect - lastAspect) > 0.0001

      if (!initialized) {
        deriveTargets(camera)
        initialized = true
        startAt = performance.now() + (prefersReducedMotion ? 0 : MOTION_DELAY_MS)
      } else if (aspectChanged) {
        deriveTargets(camera)
        if (completed || prefersReducedMotion) {
          camera.position.copy(toEye)
          camera.lookAt(toTarget)
        }
      }

      if (!completed) {
        const now = performance.now()
        if (prefersReducedMotion) {
          camera.position.copy(toEye)
          camera.lookAt(toTarget)
          completed = true
        } else if (now < startAt) {
          camera.position.copy(fromEye)
          camera.lookAt(fromTarget)
        } else {
          const linear = Math.min(1, (now - startAt) / MOTION_DURATION_MS)
          const eased = smootherStep(linear)
          camera.position.lerpVectors(fromEye, toEye, eased)
          camera.position.z += Math.sin(Math.PI * eased) * MOTION_ARC_HEIGHT_GU
          const target = new THREE.Vector3().lerpVectors(fromTarget, toTarget, eased)
          camera.lookAt(target)
          if (linear >= 1) completed = true
        }
      } else {
        // Keep the contextual pose stable if the base preview recomputes Camera
        // v2 after a resize. There is no ongoing flyaround or idle movement.
        camera.position.copy(toEye)
        camera.lookAt(toTarget)
      }
    }

    return originalRender.call(this, scene, camera)
  }

  return () => {
    THREE.WebGLRenderer.prototype.render = originalRender
  }
}
