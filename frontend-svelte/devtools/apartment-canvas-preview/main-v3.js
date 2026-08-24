import * as THREE from 'three'
import geometryScene from '../apartment-whitebox/generated/geometry-scene.json'
import { adaptGeometryScene } from '../apartment-whitebox/adapter.js'
import { addApartmentFurnitureIdentity } from './furniture-v1.js'

// Transitional preview compositor: capture the shell's accepted world group,
// then layer production-intent furniture into the exact same Three.js scene.
// This keeps the accepted shell implementation frozen while #182 is under
// visual review; the layers can be consolidated after acceptance.
let apartmentWorld = null
const originalAdd = THREE.Object3D.prototype.add
THREE.Object3D.prototype.add = function (...objects) {
  const result = originalAdd.apply(this, objects)
  if (this.type === 'Scene' && apartmentWorld === null) {
    apartmentWorld = objects.find((object) => object?.type === 'Group') ?? null
  }
  return result
}

try {
  await import('./main-v2.js')
} finally {
  THREE.Object3D.prototype.add = originalAdd
}

if (!apartmentWorld) throw new Error('Apartment Canvas furniture pass could not capture the accepted shell world')

const data = adaptGeometryScene(geometryScene)
addApartmentFurnitureIdentity(apartmentWorld, data)

document.querySelector('.preview-title small').textContent = 'Furniture identity v1 · static production preview'

const patchDebugTitle = () => {
  const panel = document.querySelector('#debug-panel')
  if (panel && !panel.hidden && panel.textContent) {
    panel.textContent = panel.textContent.replace('architectural shell v2', 'furniture identity v1')
  }
}
patchDebugTitle()
window.addEventListener('resize', () => requestAnimationFrame(patchDebugTitle))
