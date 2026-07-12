// Ambient audio guard.
//
// Ambient playback is Sonos-only. This module intentionally does not create a
// browser Audio element; it only cleans up any legacy tab-local audio that may
// have been started by an older bundle before a hot reload or deployment.

import { ambient } from './stores/ambient.js'

/** @type {HTMLAudioElement | null} */
let audio = null

function silenceBrowserAudio() {
  if (!audio) return
  audio.pause()
  audio.removeAttribute('src')
  audio.load()
  audio = null
}

/**
 * Initialize the ambient audio guard.
 * @returns {() => void} Cleanup function.
 */
export function initAmbientAudio() {
  const unsubscribe = ambient.subscribe(() => {
    silenceBrowserAudio()
  })

  return () => {
    unsubscribe()
    silenceBrowserAudio()
  }
}
