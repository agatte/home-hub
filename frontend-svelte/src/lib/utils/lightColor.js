/**
 * Convert Hue hue/sat/bri values to an HSL CSS string.
 * @param {number} hue - 0-65535
 * @param {number} sat - 0-254
 * @param {number} bri - 0-254
 * @returns {string} CSS hsl() value
 */
export function hueToHsl(hue, sat, bri) {
  const h = (hue / 65535) * 360
  const s = (sat / 254) * 100
  const l = (bri / 254) * 50
  return `hsl(${h}, ${s}%, ${Math.max(l, 20)}%)`
}

/**
 * Convert mirek color temperature to an approximate CSS rgb() string.
 * 500 mirek (2000K) = warm orange, 153 mirek (6500K) = cool blue-white
 * @param {number} ct - 153-500 mirek
 * @returns {string} CSS rgb() value
 */
export function ctToColor(ct) {
  const t = (ct - 153) / (500 - 153) // 0 = cool, 1 = warm
  const r = Math.round(255 - t * 30)
  const g = Math.round(220 - t * 80)
  const b = Math.round(200 - t * 140)
  return `rgb(${r}, ${g}, ${b})`
}

/**
 * Derive a CSS color string from a light state object.
 * Handles on/off, colormode ct vs hs, and fallback.
 * @param {{ on: boolean, bri?: number, hue?: number, sat?: number, ct?: number, colormode?: string }} state
 * @returns {string} CSS color value
 */
export function lightStateToCSS(state) {
  if (!state?.on) return 'rgba(80, 80, 90, 0.4)'
  if (state.colormode === 'ct' && state.ct) return ctToColor(state.ct)
  if (state.ct && state.hue == null) return ctToColor(state.ct)
  if (state.hue != null && state.sat != null) {
    return hueToHsl(state.hue, state.sat, state.bri ?? 200)
  }
  return 'rgba(80, 80, 90, 0.4)'
}
