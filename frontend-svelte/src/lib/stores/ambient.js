import { writable } from 'svelte/store'

/**
 * @typedef {Object} AmbientState
 * @property {boolean} playing
 * @property {string|null} sound - filename
 * @property {string|null} [sound_url] - server-resolved URL (handles /static/ambient vs /static/ambient-long)
 * @property {string|null} sound_label
 * @property {number} volume - 0.0-1.0
 * @property {string} source - "manual"|"mode"|"weather"
 * @property {boolean} weather_override
 * @property {Array<{filename: string, label: string}>} available_sounds
 * @property {Record<string, string>} mode_sounds
 * @property {Record<string, boolean>} mode_auto_play
 * @property {boolean} weather_reactive
 * @property {boolean} sonos_enabled - master toggle: when true and Sonos is reachable, ambient plays on Sonos and per-tab audio is silenced
 * @property {boolean} sonos_ambient_active - backend has Sonos actually playing right now (consumed by ambientAudio.js to gate browser playback)
 * @property {number} sonos_present_volume - default Sonos level when user is nearby (0-60)
 * @property {number} sonos_away_volume - Sonos level when camera reports absent (follow-me ramp)
 * @property {Record<string, number>} sonos_mode_volume_overrides - per-mode override; missing modes fall back to sonos_present_volume
 * @property {string[]} suppressed_modes - modes where ambient is fully off on both surfaces (watching/gameday/sleeping)
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
  sonos_enabled: true,
  sonos_ambient_active: false,
  sonos_present_volume: 12,
  sonos_away_volume: 28,
  sonos_mode_volume_overrides: {},
  suppressed_modes: ['watching', 'gameday', 'sleeping'],
}

/** @type {import('svelte/store').Writable<AmbientState>} */
export const ambient = writable(initial)
