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
 * The backend already projects it to General while Home, and this guard keeps
 * stale/compatibility payloads from reintroducing Idle into the UI.
 * @param {unknown} activity
 * @returns {string | null}
 */
export function normalizeActivity(activity) {
  if (activity == null || activity === '') return null
  const value = String(activity)
  return value === 'idle' ? 'general' : value
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
  return {
    mode: data.current_mode ?? 'idle',
    source: data.mode_source ?? 'time',
    house_state: data.house_state ?? null,
    activity: normalizeActivity(data.activity),
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
  return {
    ...prev,
    mode: data.mode ?? data.current_mode ?? prev.mode,
    source: data.source ?? data.mode_source ?? prev.source,
    house_state: Object.prototype.hasOwnProperty.call(data, 'house_state')
      ? data.house_state ?? null
      : prev.house_state,
    activity: Object.prototype.hasOwnProperty.call(data, 'activity')
      ? normalizeActivity(data.activity)
      : prev.activity,
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
