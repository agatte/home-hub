// Local visual representation of declared scene values, never live telemetry.
import { sceneTemperatureColor } from './sceneCards.js'

/** @typedef {{on?:boolean,bri?:number,hue?:number,sat?:number,ct?:number}} DraftState */
export const SCENE_FIXTURES = [
  { id: '2', room: 'Bedroom', name: 'Left lamp' },
  { id: '5', room: 'Bedroom', name: 'Right lamp' },
  { id: '1', room: 'Living room', name: 'Lamp' },
  { id: '6', room: 'Living room', name: 'Plant Wash' },
  { id: '3', room: 'Kitchen', name: 'Front' },
  { id: '4', room: 'Kitchen', name: 'Back' },
]

/** @param {unknown} value @param {number} min @param {number} max */
function inRange(value, min, max) {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max
}

/** Explicit exclusive color modes; ambiguous/partial saved values are not guessed.
 * @param {DraftState | undefined} state */
export function draftColorMode(state) {
  if (!state) return 'unspecified'
  if (inRange(state.ct, 153, 500) && state.hue == null && state.sat == null) return 'temperature'
  if (state.ct == null && inRange(state.hue, 0, 65535) && inRange(state.sat, 0, 254)) return 'color'
  return 'unspecified'
}

/** Set only the selected draft's color fields, preserving power/brightness and
 * unrelated metadata. Invalid input returns the original state.
 * @template {DraftState} T
 * @param {T} state @param {{ct:number}|{hue:number,sat:number}} color
 * @returns {T}
 */
export function withDraftColor(state, color) {
  const { ct, hue, sat, ...rest } = state
  if ('ct' in color && inRange(color.ct, 153, 500)) return /** @type {T} */ ({ ...rest, ct: color.ct })
  if ('hue' in color && inRange(color.hue, 0, 65535) && inRange(color.sat, 0, 254)) return /** @type {T} */ ({ ...rest, hue: color.hue, sat: color.sat })
  return state
}

/** @param {Record<string,DraftState>|null|undefined} states */
export function scenePreviewRows(states) {
  return SCENE_FIXTURES.map(fixture => {
    const state = states?.[fixture.id]
    const power = state?.on === true ? 'On' : state?.on === false ? 'Off' : 'Not specified'
    const brightness = state?.on === true && inRange(state.bri, 1, 254) ? Math.round((state.bri ?? 0) / 254 * 100) : null
    const mode = draftColorMode(state)
    const color = mode === 'temperature' ? sceneTemperatureColor(state?.ct ?? 350)
      : mode === 'color' ? `hsl(${(state?.hue ?? 0) / 65535 * 360}, ${(state?.sat ?? 0) / 254 * 100}%, 62%)` : null
    const colorLabel = mode === 'temperature' ? `${Math.round(1000000 / (state?.ct ?? 350))} K`
      : mode === 'color' ? `Hue ${Math.round((state?.hue ?? 0) / 65535 * 360)}°, ${Math.round((state?.sat ?? 0) / 254 * 100)}% saturation` : 'Color not specified'
    // Exact valid color fields travel with the reviewed scene so the existing
    // fresh-read comparison also notices a changed declared color.
    const colorKey = mode === 'temperature' ? [state?.ct] : mode === 'color' ? [state?.hue, state?.sat] : null
    return { ...fixture, power, brightness, color, colorLabel, colorKey }
  })
}
