import { writable } from 'svelte/store'

/**
 * Rule-suggestion store. Expiry is now server-driven via
 * `mode_suggestion_dismissed` (60min server-side auto-expire on the
 * automation tick) — the 20s client-side auto-hide was removed when the
 * inline Home banner became the primary surface.
 *
 * @typedef {Object} ModeSuggestion
 * @property {number} suggestion_id  - rule_suggestions.id, used for race-safe accept
 * @property {number} rule_id
 * @property {string} predicted_mode
 * @property {number} confidence     - integer percent (0-100)
 * @property {number} sample_count
 * @property {string} message
 */

/** @type {import('svelte/store').Writable<ModeSuggestion | null>} */
export const modeSuggestion = writable(null)

/** @param {ModeSuggestion} data */
export function showModeSuggestion(data) {
  modeSuggestion.set(data)
}

export function dismissModeSuggestion() {
  modeSuggestion.set(null)
}
