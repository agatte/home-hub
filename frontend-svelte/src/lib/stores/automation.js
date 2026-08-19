import { writable } from 'svelte/store'

/**
 * @typedef {Object} DNDState
 * @property {boolean} enabled
 * @property {string | null} expiry_utc
 * @property {number} minutes_remaining
 */

/**
 * @typedef {Object} AutomationState
 * @property {string} mode Legacy automation mode retained for compatibility/control surfaces.
 * @property {string} source
 * @property {string | null} house_state User-facing lifecycle state.
 * @property {string | null} activity User-facing semantic activity.
 * @property {string | null} time_period
 * @property {boolean} manual_override
 * @property {DNDState} dnd
 */

const HOUSE_STATE_LABELS = {
  away: 'Away',
  home: 'Home',
  winding_down: 'Winding Down',
  sleeping: 'Sleeping',
}

const ACTIVITY_LABELS = {
  general: 'General',
  working: 'Working',
  gaming: 'Gaming',
  watching: 'Watching',
  cooking: 'Cooking',
  relax: 'Relax',
  social: 'Social',
}

/**
 * Internal detectors may still report `idle`; it is not a user-facing Activity.
 * While Home it projects to General. Away/Sleeping never retain an Activity,
 * and compatibility payloads must not create contradictory user-facing state.
 * @param {unknown} activity
 * @param {string | null | undefined} houseState
 * @returns {string | null}
 */
export function normalizeActivity(activity, houseState = null) {
  if (activity == null || activity === '') return null
  if (houseState === 'away' || houseState === 'sleeping') return null

  const value = String(activity)
  if (value === 'idle') return houseState === 'home' ? 'general' : null
  return value
}

/**
 * @param {string | null | undefined} value
 * @param {Record<string, string>} labels
 * @returns {string | null}
 */
function readableLabel(value, labels) {
  if (!value) return null
  return labels[value] || value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

/** @param {string | null | undefined} value */
export function houseStateLabel(value) {
  return readableLabel(value, HOUSE_STATE_LABELS)
}

/** @param {string | null | undefined} value */
export function activityLabel(value) {
  return readableLabel(normalizeActivity(value), ACTIVITY_LABELS)
}

/**
 * Convert the REST automation status shape into the shared frontend state.
 * @param {Record<string, any>} data
 * @returns {AutomationState}
 */
export function automationStateFromStatus(data) {
  const houseState = data.house_state ?? null

  return {
    mode: data.current_mode ?? 'idle',
    source: data.mode_source ?? 'time',
    house_state: houseState,
    activity: normalizeActivity(data.activity, houseState),
    time_period: data.time_period ?? null,
    manual_override: !!data.manual_override,
    dnd: {
      enabled: !!data.dnd_enabled,
      expiry_utc: data.dnd_expiry_utc ?? null,
      minutes_remaining: data.dnd_minutes_remaining ?? 0,
    },
  }
}

/**
 * Merge a live `mode_update` payload while preserving fields not present in
 * that update. Accept both live (`mode`/`source`) and REST-style names so the
 * compatibility boundary is explicit in one place.
 * @param {AutomationState} prev
 * @param {Record<string, any>} data
 * @returns {AutomationState}
 */
export function mergeAutomationUpdate(prev, data) {
  const hasHouseState = Object.prototype.hasOwnProperty.call(data, 'house_state')
  const hasActivity = Object.prototype.hasOwnProperty.call(data, 'activity')
  const houseState = hasHouseState ? data.house_state ?? null : prev.house_state
  const activity = hasActivity
    ? normalizeActivity(data.activity, houseState)
    : (houseState === 'away' || houseState === 'sleeping' ? null : prev.activity)

  return {
    ...prev,
    mode: data.mode ?? data.current_mode ?? prev.mode,
    source: data.source ?? data.mode_source ?? prev.source,
    house_state: houseState,
    activity,
    time_period: Object.prototype.hasOwnProperty.call(data, 'time_period')
      ? data.time_period ?? null
      : prev.time_period,
    manual_override: typeof data.manual_override === 'boolean'
      ? data.manual_override
      : prev.manual_override,
  }
}

/** @type {AutomationState} */
export const initialAutomationState = {
  mode: 'idle',
  source: 'time',
  house_state: null,
  activity: null,
  time_period: null,
  manual_override: false,
  dnd: {
    enabled: false,
    expiry_utc: null,
    minutes_remaining: 0,
  },
}

/** @type {import('svelte/store').Writable<AutomationState>} */
export const automation = writable(initialAutomationState)
