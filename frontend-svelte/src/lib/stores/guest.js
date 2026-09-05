/** @typedef {{ light_id: string | number, name: string, on: boolean, bri?: number, hue?: number, sat?: number, ct?: number }} GuestLight */
/** @typedef {{ state?: string, track?: string, artist?: string, album?: string, volume?: number, mute?: boolean, has_art?: boolean }} GuestSonos */
/** @typedef {{ mode: string, source: string | null, manual_override: boolean, lights: GuestLight[], sonos: GuestSonos }} GuestState */

import { writable } from 'svelte/store'

/** @type {GuestState} */
const EMPTY_STATE = {
  mode: 'idle',
  source: null,
  manual_override: false,
  lights: [],
  sonos: { state: 'disconnected', has_art: false },
}

export const guestState = writable(EMPTY_STATE)

let timer = null
let subscribers = 0

export async function refreshGuestState() {
  try {
    const response = await fetch('/api/guest/state', { cache: 'no-store' })
    if (!response.ok) return false
    const body = await response.json()
    guestState.set({
      mode: body.mode ?? 'idle',
      source: body.source ?? null,
      manual_override: !!body.manual_override,
      lights: Array.isArray(body.lights) ? body.lights : [],
      sonos: body.sonos ?? EMPTY_STATE.sonos,
    })
    return true
  } catch {
    return false
  }
}

export function initGuestState(intervalMs = 2000) {
  subscribers += 1
  refreshGuestState()
  if (!timer) {
    timer = setInterval(refreshGuestState, intervalMs)
  }
  return () => {
    subscribers = Math.max(0, subscribers - 1)
    if (subscribers === 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }
}
