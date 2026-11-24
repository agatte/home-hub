import { filterScenes } from './lightingModel.js'
import { ctToColor, hueToHsl } from '../utils/lightColor.js'

/** Saved colors only: no guesses for native Hue scenes without a manifest.
 * @param {any} raw
 * @returns {string[]}
 */
export function scenePalette(raw) {
  if (!raw || raw.source === 'bridge' || !raw.lights || typeof raw.lights !== 'object' || Array.isArray(raw.lights)) return []
  const colors = new Set()
  for (const state of Object.values(raw.lights)) {
    if (!state || state.on !== true) continue
    if (Number.isFinite(state.ct) && state.ct >= 153 && state.ct <= 500) {
      colors.add(ctToColor(state.ct))
    } else if (Number.isFinite(state.hue) && state.hue >= 0 && state.hue <= 65535 &&
        Number.isFinite(state.sat) && state.sat >= 0 && state.sat <= 254) {
      // Display the declared hue rather than making very dim colors invisible.
      colors.add(hueToHsl(state.hue, state.sat, 220))
    }
  }
  return [...colors].slice(0, 6)
}

/** Keep all distinct scene IDs. Only same-name native scenes share a card;
 * no automatic multi-room recall or deletion.
 * @param {unknown} input
 * @param {{category?:string,search?:string}} filters
 */
export function sceneCards(input, filters = {}) {
  const rows = Array.isArray(input) ? input : []
  const cards = new Map()
  for (const scene of filterScenes(rows, filters)) {
    const raw = rows.find(row => row?.id === scene.id && row?.source === scene.source)
    const key = scene.source === 'bridge' ? 'bridge:' + scene.name.toLocaleLowerCase() : scene.source + ':' + scene.id
    const group = typeof raw?.group_name === 'string' && raw.group_name.trim()
      ? raw.group_name.trim()
      : typeof raw?.group_id === 'string' && raw.group_id
        ? 'Hue group …' + raw.group_id.slice(-6)
        : 'Hue scene …' + scene.id.slice(-6)
    const variant = { id: scene.id, label: group }
    const existing = cards.get(key)
    if (existing) {
      existing.variants.push(variant)
    } else {
      cards.set(key, { ...scene, key, palette: scenePalette(raw), variants: [variant] })
    }
  }
  return [...cards.values()]
}

/** All color strings originate in the numeric conversion functions above.
 * @param {string[]} palette
 */
export function sceneCardBackground(palette) {
  if (!palette.length) return ''
  const colors = palette.length === 1 ? [palette[0], palette[0]] : palette
  return 'linear-gradient(120deg, rgba(12,19,19,.78), rgba(12,19,19,.88)), linear-gradient(125deg, ' + colors.join(', ') + ')'
}
