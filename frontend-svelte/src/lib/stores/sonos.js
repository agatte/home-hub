import { writable } from 'svelte/store'

/**
 * @typedef {Object} SonosState
 * @property {string} state — "PLAYING" | "PAUSED_PLAYBACK" | "STOPPED" | ...
 * @property {string} track
 * @property {string} artist
 * @property {string} album
 * @property {string} art_url
 * @property {number} volume
 * @property {boolean} mute
 */

/** @type {SonosState} */
const initial = {
  state: 'STOPPED',
  track: '',
  artist: '',
  album: '',
  art_url: '',
  volume: 0,
  mute: false,
}

/** @type {import('svelte/store').Writable<SonosState>} */
export const sonos = writable(initial)
