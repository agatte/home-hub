// Ambient audio playback engine.
// Subscribes to the ambient store and manages an HTML5 Audio element.
// Audio loops seamlessly and resumes after page reloads via persisted state.

import { ambient } from './stores/ambient.js'

/** @type {HTMLAudioElement | null} */
let audio = null
let currentSrc = ''
let pendingPlay = false

// Track user interaction for autoplay policy compliance
let userHasInteracted = false

function markInteracted() {
  userHasInteracted = true
  document.removeEventListener('click', markInteracted)
  document.removeEventListener('keydown', markInteracted)

  // Retry pending play if autoplay was blocked
  if (pendingPlay && audio) {
    audio.play().catch(() => {})
    pendingPlay = false
  }
}

function ensureListeners() {
  if (!userHasInteracted) {
    document.addEventListener('click', markInteracted)
    document.addEventListener('keydown', markInteracted)
  }
}

function ensureAudio() {
  if (!audio) {
    audio = new Audio()
    audio.loop = true
    audio.preload = 'auto'
  }
  return audio
}

/**
 * Initialize the ambient audio engine. Subscribes to the ambient store
 * and plays/pauses/swaps audio accordingly.
 * @returns {() => void} Cleanup function (unsubscribe + stop audio)
 */
export function initAmbientAudio() {
  ensureListeners()

  const unsubscribe = ambient.subscribe((state) => {
    if (!state) return

    const a = ensureAudio()
    const targetSrc = state.sound ? `/static/ambient/${state.sound}` : ''

    // Update volume always
    a.volume = state.volume

    if (state.playing && state.sound) {
      // Need to play — check if source changed
      if (targetSrc !== currentSrc) {
        currentSrc = targetSrc
        a.src = targetSrc
        a.load()
      }

      if (a.paused) {
        const playPromise = a.play()
        if (playPromise) {
          playPromise.catch(() => {
            // Autoplay blocked — will retry on user interaction
            pendingPlay = true
          })
        }
      }
    } else {
      // Should not be playing
      if (!a.paused) {
        a.pause()
      }
      pendingPlay = false
    }
  })

  return () => {
    unsubscribe()
    if (audio) {
      audio.pause()
      audio.src = ''
      audio = null
    }
    currentSrc = ''
    pendingPlay = false
  }
}
