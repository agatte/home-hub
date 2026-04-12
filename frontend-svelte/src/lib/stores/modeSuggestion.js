import { writable } from 'svelte/store'

/**
 * @typedef {Object} ModeSuggestion
 * @property {number} rule_id
 * @property {string} predicted_mode
 * @property {number} confidence
 * @property {number} sample_count
 * @property {string} message
 */

/** @type {import('svelte/store').Writable<ModeSuggestion | null>} */
export const modeSuggestion = writable(null)

/** @type {ReturnType<typeof setTimeout> | null} */
let suggestionTimer = null

/** @param {ModeSuggestion} data */
export function showModeSuggestion(data) {
  if (suggestionTimer) clearTimeout(suggestionTimer)
  modeSuggestion.set(data)
  suggestionTimer = setTimeout(() => {
    modeSuggestion.set(null)
    suggestionTimer = null
  }, 20_000)
}

export function dismissModeSuggestion() {
  if (suggestionTimer) {
    clearTimeout(suggestionTimer)
    suggestionTimer = null
  }
  modeSuggestion.set(null)
}
