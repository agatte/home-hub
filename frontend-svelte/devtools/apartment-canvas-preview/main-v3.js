import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addApartmentFurnitureIdentity } from './furniture-v1.js'

// Transitional preview compositor: capture the shell's accepted world group,
// then layer production-intent furniture into the exact same Three.js scene.
// Keep this bootstrap deliberately boring: the project build target does not
// allow top-level await, and a furniture-layer failure must not silently blank
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
    panel.textContent = panel.textContent.replace('architectural shell v2', 'furniture identity v1')
  }
}

import('./main-v2.js')
  .then(() => {
    restoreObjectAdd()
    if (!apartmentWorld) {
      throw new Error('Apartment Canvas furniture pass could not capture the accepted shell world')
    }

    const data = adaptGeometryScene(geometryScene)
    addApartmentFurnitureIdentity(apartmentWorld, data)
    patchPreviewTitle('Furniture identity v1 · static production preview')
    patchDebugTitle()
    window.addEventListener('resize', () => requestAnimationFrame(patchDebugTitle))
  })
  .catch((error) => {
    restoreObjectAdd()
    console.error('Apartment Canvas furniture preview failed', error)
    patchPreviewTitle(`Furniture preview error · ${error.message}`)
  })
