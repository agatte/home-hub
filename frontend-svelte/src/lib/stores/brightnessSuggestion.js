import { writable } from 'svelte/store'

/**
 * Brightness-suggestion store. Server-driven lifecycle: rule_suggestions
 * rows with kind="brightness" are broadcast via the `brightness_suggestion`
 * WS event; resolution comes via accept/dismiss POSTs against the
 * /api/rules/brightness-suggestion/{accept|dismiss}/{id} endpoints.
 *
 * @typedef {Object} BrightnessSuggestionPayload
 * @property {string} [scope]
 * @property {string} [room]
 * @property {string} [light_id]
 * @property {string} mode
 * @property {string} period
 * @property {string} weather_class
 * @property {number} [suggested_bri]
 * @property {number} [target_pct]
 * @property {Object.<string, number>} [light_targets]
 * @property {Object.<string, number>} [base_targets]
 * @property {number} [base_bri]
 * @property {number} [suggested_multiplier]
 * @property {number} sample_count
 *
 * @typedef {Object} BrightnessSuggestion
 * @property {number} id           - rule_suggestions.id, used for race-safe accept
 * @property {string} kind         - always "brightness"
 * @property {number} confidence   - integer percent (0-100)
 * @property {number} sample_count
 * @property {BrightnessSuggestionPayload} payload
 */

/** @type {import('svelte/store').Writable<BrightnessSuggestion | null>} */
export const brightnessSuggestion = writable(null)

/** @param {BrightnessSuggestion} data */
export function showBrightnessSuggestion(data) {
  brightnessSuggestion.set(data)
}

export function dismissBrightnessSuggestion() {
  brightnessSuggestion.set(null)
}
