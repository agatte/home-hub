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
 * @property {boolean} manual_override Internal override latch, including autonomous owners.
 * @property {string | null} override_source Source that owns the override latch, if any.
 * @property {boolean} override_user_owned True only for explicit user-owned override intent.
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

const AUTO_OVERRIDE_SOURCE_LABELS = {
  late_night_rescue: 'Late-night recovery',
  ambient_relax: 'Ambient context',
  physical_context_relax: 'Couch context',
  zone_posture_rule: 'Posture context',
  watching_sleep_guard: 'Sleep context',
  behavioral_predictor: 'Learned context',
  fusion_can_override: 'Sensor context',
  fusion_auto_apply: 'Sensor context',
  'gameday:auto': 'Game Day schedule',
  'gameday:auto:pregame': 'Game Day schedule',
  internal: 'Automation',
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
 * Describe who owns the effective mode without conflating HomeHub's internal
 * autonomous override latch with explicit user intent.
 * @param {AutomationState} state
 * @returns {string}
 */
export function automationSourceLabel(state) {
  if (state.override_user_owned) return 'Manual override'
  if (state.manual_override && state.override_source) {
    const label = AUTO_OVERRIDE_SOURCE_LABELS[state.override_source] || 'Automation'
    return `Auto (${label})`
  }
  return `Auto (${state.source || 'time'})`
}

/**
 * Convert the REST automation status shape into the shared frontend state.
 * @param {Record<string, any>} data
 * @returns {AutomationState}
 */
export function automationStateFromStatus(data) {
  const houseState = data.house_state ?? null

  const manualOverride = !!data.manual_override
  return {
    mode: data.current_mode ?? 'idle',
    source: data.mode_source ?? 'time',
    house_state: houseState,
    activity: normalizeActivity(data.activity, houseState),
    time_period: data.time_period ?? null,
    manual_override: manualOverride,
    override_source: data.override_source ?? null,
    override_user_owned: typeof data.override_user_owned === 'boolean'
      ? data.override_user_owned
      : manualOverride,
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

  const manualOverride = typeof data.manual_override === 'boolean'
    ? data.manual_override
    : prev.manual_override
  return {
    ...prev,
    mode: data.mode ?? data.current_mode ?? prev.mode,
    source: data.source ?? data.mode_source ?? prev.source,
    house_state: houseState,
    activity,
    time_period: Object.prototype.hasOwnProperty.call(data, 'time_period')
      ? data.time_period ?? null
      : prev.time_period,
    manual_override: manualOverride,
    override_source: Object.prototype.hasOwnProperty.call(data, 'override_source')
      ? data.override_source ?? null
      : prev.override_source,
    override_user_owned: typeof data.override_user_owned === 'boolean'
      ? data.override_user_owned
      : prev.override_user_owned,
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
  override_source: null,
  override_user_owned: false,
  dnd: {
    enabled: false,
    expiry_utc: null,
    minutes_remaining: 0,
  },
}

/** @type {import('svelte/store').Writable<AutomationState>} */
export const automation = writable(initialAutomationState)
