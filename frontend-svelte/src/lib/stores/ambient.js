import { writable } from 'svelte/store'

/**
 * @typedef {Object} AmbientState
 * @property {boolean} playing
 * @property {string|null} sound - filename
 * @property {string|null} sound_label
 * @property {number} volume - 0.0-1.0
 * @property {string} source - "manual"|"mode"|"weather"
 * @property {boolean} weather_override
 * @property {Array<{filename: string, label: string}>} available_sounds
 * @property {Record<string, string>} mode_sounds
 * @property {Record<string, boolean>} mode_auto_play
 * @property {boolean} weather_reactive
 */

/** @type {AmbientState} */
const initial = {
  playing: false,
  sound: null,
  sound_label: null,
  volume: 0.3,
  source: 'manual',
  weather_override: false,
  available_sounds: [],
  mode_sounds: {},
  mode_auto_play: {},
  weather_reactive: true,
}

/** @type {import('svelte/store').Writable<AmbientState>} */
export const ambient = writable(initial)
