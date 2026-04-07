import { writable } from 'svelte/store'

/**
 * @typedef {Object} AutomationState
 * @property {string} mode
 * @property {string} source
 * @property {boolean} manual_override
 * @property {string} [social_style]
 */

/** @type {AutomationState} */
const initial = {
  mode: 'idle',
  source: 'time',
  manual_override: false,
  social_style: 'color_cycle',
}

/** @type {import('svelte/store').Writable<AutomationState>} */
export const automation = writable(initial)
