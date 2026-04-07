import { writable } from 'svelte/store'

/**
 * @typedef {Object} Light
 * @property {string} light_id
 * @property {string} name
 * @property {boolean} on
 * @property {number} bri
 * @property {number} hue
 * @property {number} sat
 * @property {boolean} reachable
 */

/** @type {import('svelte/store').Writable<Record<string, Light>>} */
export const lights = writable({})

/**
 * Merge a single light update into the store (from WebSocket light_update).
 * @param {Light} light
 */
export function applyLightUpdate(light) {
  lights.update((prev) => ({ ...prev, [light.light_id]: light }))
}

/**
 * Replace the full lights map (from initial /api/lights fetch).
 * @param {Light[]} list
 */
export function setLightsFromList(list) {
  /** @type {Record<string, Light>} */
  const map = {}
  for (const light of list) map[light.light_id] = light
  lights.set(map)
}

/**
 * Optimistic partial update applied immediately, before the WS round-trip.
 * @param {string} lightId
 * @param {Partial<Light>} patch
 */
export function optimisticLightPatch(lightId, patch) {
  lights.update((prev) => ({
    ...prev,
    [lightId]: { ...prev[lightId], ...patch },
  }))
}
