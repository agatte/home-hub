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

    // Sonos is the primary surface — when the backend has Sonos playing
    // ambient (or is about to), silence the per-tab HTMLAudio so we don't
    // double up. `sonos_ambient_pending` closes the broadcast race: the
    // first ambient_update after a mode flip arrives BEFORE Sonos confirms
    // playback, so without the pending gate the device the user just
    // touched would win on autoplay permission and play locally before the
    // second broadcast flipped `active` true. If Sonos ultimately fails,
    // the backend clears pending and re-broadcasts so we fall through to
    // local playback as the documented fallback.
    if (state.sonos_ambient_active || state.sonos_ambient_pending) {
      if (audio && !audio.paused) audio.pause()
      pendingPlay = false
      return
    }

    const a = ensureAudio()
    // Server-resolved URL handles short fallbacks (/static/ambient/) vs
    // long-form user files (/static/ambient-long/). Fall back to the legacy
    // path if the server hasn't been updated yet.
    const targetSrc = state.sound
      ? (state.sound_url || `/static/ambient/${state.sound}`)
      : ''

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
