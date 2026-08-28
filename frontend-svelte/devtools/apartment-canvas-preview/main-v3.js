import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addApartmentStaticPolishV1 } from './polish-v1.js'
import { addBedroomDesignPassV1 } from './bedroom-v1.js'
import { addLivingRoomSofaV1 } from './living-room-sofa-v1.js'

// Transitional preview compositor: capture the shell's accepted world group,
// then layer production-intent furniture/details into the exact same Three.js
// scene. Keep this bootstrap deliberately boring: the project build target does
// not allow top-level await, and a detail-layer failure must not silently blank
// the already-accepted architectural shell.
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

function patchDebugTitle() {
  const panel = document.querySelector('#debug-panel')
  if (panel && !panel.hidden && panel.textContent) {
    panel.textContent = panel.textContent.replace('architectural shell v2', 'static apartment polish v1')
  }
}

import('./main-v2.js')
  .then(() => {
    restoreObjectAdd()
    if (!apartmentWorld) {
      throw new Error('Apartment Canvas static-polish pass could not capture the accepted shell world')
    }

    const data = adaptGeometryScene(geometryScene)
    addApartmentStaticPolishV1(apartmentWorld, data)
    addBedroomDesignPassV1(apartmentWorld, data)
    addLivingRoomSofaV1(apartmentWorld)
    patchPreviewTitle('Bedroom + measured Living Room sofa baseline · static production preview')
    patchDebugTitle()
    window.addEventListener('resize', () => requestAnimationFrame(patchDebugTitle))
  })
  .catch((error) => {
    restoreObjectAdd()
    console.error('Apartment Canvas static-polish preview failed', error)
    patchPreviewTitle(`Apartment polish preview error · ${error.message}`)
  })
