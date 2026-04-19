import { writable } from 'svelte/store'

/**
 * @typedef {Object} AutomationState
 * @property {string} mode
 * @property {string} source
 * @property {boolean} manual_override
 */

/** @type {AutomationState} */
const initial = {
  mode: 'idle',
  source: 'time',
  manual_override: false,
}

/** @type {import('svelte/store').Writable<AutomationState>} */
export const automation = writable(initial)
