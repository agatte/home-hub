import { filterScenes } from './lightingModel.js'


/** Approximate saved white temperature as a display swatch, not a calibrated bulb measurement.
 * @param {number} mirek
 */
export function sceneTemperatureColor(mirek) {
  const t = 10000 / mirek // Kelvin / 100
  const clamp = (n) => Math.round(Math.max(0, Math.min(255, n)))
  const r = t <= 66 ? 255 : 329.698727446 * (t - 60) ** -0.1332047592
  const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * (t - 60) ** -0.0755148492
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307
  return `rgb(${clamp(r)}, ${clamp(g)}, ${clamp(b)})`
}

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
      colors.add(sceneTemperatureColor(state.ct))
    } else if (Number.isFinite(state.hue) && state.hue >= 0 && state.hue <= 65535 &&
        Number.isFinite(state.sat) && state.sat >= 0 && state.sat <= 254) {
      // Display the declared hue rather than making very dim colors invisible.
      colors.add(`hsl(${state.hue / 65535 * 360}, ${state.sat / 254 * 100}%, 62%)`)
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
  // Keep the lower controls on a dark base; let light bloom along the upper-right edge.
  return 'linear-gradient(135deg, rgba(12,15,19,.80) 0%, rgba(12,15,19,.65) 42%, rgba(12,15,19,.25) 70%, rgba(12,15,19,.70) 100%), linear-gradient(115deg, ' + colors.join(', ') + ')'
}

/** Same saved-scene background for compact shortcuts and library cards.
 * @param {unknown} input
 * @param {string} id
 */
export function sceneBackgroundForId(input, id) {
  const rows = Array.isArray(input) ? input : []
  return sceneCardBackground(scenePalette(rows.find(row => row?.id === id)))
}
