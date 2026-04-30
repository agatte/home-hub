import { writable } from 'svelte/store'

/**
 * @typedef {Object} DNDState
 * @property {boolean} enabled
 * @property {string | null} expiry_utc
 * @property {number} minutes_remaining
 */

/**
 * @typedef {Object} AutomationState
 * @property {string} mode
 * @property {string} source
 * @property {boolean} manual_override
 * @property {DNDState} dnd
 */

/** @type {AutomationState} */
const initial = {
  mode: 'idle',
  source: 'time',
  manual_override: false,
  dnd: {
    enabled: false,
    expiry_utc: null,
    minutes_remaining: 0,
  },
}

/** @type {import('svelte/store').Writable<AutomationState>} */
export const automation = writable(initial)
