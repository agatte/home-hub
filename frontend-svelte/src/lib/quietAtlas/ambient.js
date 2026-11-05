import { writable } from 'svelte/store'
import { houseStateLabel, activityLabel, normalizeActivity } from '../stores/automation.js'
import { isQuietAtlasReadOnlyPreview } from './navigation.js'

export const AMBIENT_VIEWPORT = '(min-width: 900px) and (orientation: landscape)'

// First #15 candidate only: future functional routes must explicitly opt in.
export function ambientRouteEligible(pathname) {
  return pathname.startsWith('/quiet-atlas/') &&
    !pathname.startsWith('/quiet-atlas/music/artist-review') &&
    isQuietAtlasReadOnlyPreview(pathname)
}

// A receipt is independent of REST/optimistic automation projections. Only the
// accepted live mode_update path may populate it; every socket boundary clears it.
/** @type {import('svelte/store').Writable<{ house_state: string, activity: string | null } | null>} */
const receipt = writable(null)
export const ambientContext = { subscribe: receipt.subscribe }
export function resetAmbientContext() { receipt.set(null) }
export function receiveAmbientContext(data) {
  receipt.update(previous => {
    const hasState = Object.prototype.hasOwnProperty.call(data, 'house_state')
    if (!hasState && !previous) return null
    const state = hasState ? data.house_state : previous?.house_state
    if (!['home', 'away', 'winding_down', 'sleeping'].includes(state)) return null
    // A new state receipt never inherits an omitted activity from an old state.
    const activity = Object.prototype.hasOwnProperty.call(data, 'activity')
      ? normalizeActivity(data.activity, state)
      : hasState ? null : previous?.activity ?? null
    return { house_state: state, activity }
  })
}

// Only show status reported over the active HomeHub connection. Never infer a room.
export function ambientContent(connected, context) {
  const state = connected && ['home', 'away', 'winding_down', 'sleeping'].includes(context?.house_state)
    ? context?.house_state : null
  return {
    house: state ? houseStateLabel(state) : null,
    activity: state ? activityLabel(normalizeActivity(context.activity, state)) : null,
  }
}

export function ambientClockText(now) {
  return now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function ambientDateText(now) {
  return now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
}
