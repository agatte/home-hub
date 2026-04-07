import { writable } from 'svelte/store'

/**
 * @typedef {Object} MusicSuggestion
 * @property {string} mode
 * @property {string} title
 * @property {string} [message]
 */

/**
 * @typedef {Object} MusicAutoPlayed
 * @property {string} mode
 * @property {string} title
 */

/** @type {import('svelte/store').Writable<MusicSuggestion | null>} */
export const musicSuggestion = writable(null)

/** @type {import('svelte/store').Writable<MusicAutoPlayed | null>} */
export const musicAutoPlayed = writable(null)

/** @type {ReturnType<typeof setTimeout> | null} */
let suggestionTimer = null
/** @type {ReturnType<typeof setTimeout> | null} */
let autoPlayedTimer = null

// Parity with React MusicContext: suggestion auto-clears after 15s,
// auto-played toast auto-clears after 5s.
/** @param {MusicSuggestion} data */
export function showMusicSuggestion(data) {
  if (suggestionTimer) clearTimeout(suggestionTimer)
  musicSuggestion.set(data)
  suggestionTimer = setTimeout(() => {
    musicSuggestion.set(null)
    suggestionTimer = null
  }, 15_000)
}

/** @param {MusicAutoPlayed} data */
export function showMusicAutoPlayed(data) {
  if (autoPlayedTimer) clearTimeout(autoPlayedTimer)
  musicAutoPlayed.set(data)
  autoPlayedTimer = setTimeout(() => {
    musicAutoPlayed.set(null)
    autoPlayedTimer = null
  }, 5_000)
}

export function dismissMusicSuggestion() {
  if (suggestionTimer) {
    clearTimeout(suggestionTimer)
    suggestionTimer = null
  }
  musicSuggestion.set(null)
}
