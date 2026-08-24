import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addApartmentStaticPolishV1 } from './polish-v1.js'
import { resolveSyntheticPreviewState } from './live-state.js'
import { addApartmentLiveStateV1 } from './live-state-v1.js'
import { installContextCameraMotionPreview } from './camera-motion-v2.js'

// Transitional preview compositor: capture the accepted shell world, then layer
// Static Apartment v1, synthetic review-only live state, and a bounded
// contextual camera transition into the exact same Three.js scene. A preview
// layer failure must not silently blank the accepted architectural baseline.
let apartmentWorld = null
const originalAdd = THREE.Object3D.prototype.add
THREE.Object3D.prototype.add = function (...objects) {
  const result = originalAdd.apply(this, objects)
  if (this.type === 'Scene' && apartmentWorld === null) {
    apartmentWorld = objects.find((object) => object?.type === 'Group') ?? null
  }
  return result
}

function restoreObjectAdd() {
  THREE.Object3D.prototype.add = originalAdd
}

function patchPreviewTitle(text) {
  const subtitle = document.querySelector('.preview-title small')
  if (subtitle) subtitle.textContent = text
}

function patchDebugTitle(state) {
  const panel = document.querySelector('#debug-panel')
  if (panel && !panel.hidden && panel.textContent) {
    panel.textContent = panel.textContent
      .replace('architectural shell v2', 'synthetic live state v1')
      .concat(`\nsynthetic state ${state.id}`)
  }
}

const previewState = resolveSyntheticPreviewState(window.location.search)
const restoreCameraMotion = installContextCameraMotionPreview(previewState.id, window.location.search)

import('./main-v2.js')
  .then(() => {
    restoreObjectAdd()
    if (!apartmentWorld) {
      throw new Error('Apartment Canvas live-state preview could not capture the accepted shell world')
    }

    const data = adaptGeometryScene(geometryScene)
    addApartmentStaticPolishV1(apartmentWorld, data)
    addApartmentLiveStateV1(apartmentWorld, data, previewState)
    patchPreviewTitle(`Synthetic live state v1 · ${previewState.label}`)
    patchDebugTitle(previewState)
  })
  .catch((error) => {
    restoreObjectAdd()
    restoreCameraMotion()
    console.error('Apartment Canvas live-state preview failed', error)
    patchPreviewTitle(`Live-state preview error · ${error.message}`)
  })
