// pulseLinks store — correlates light_update events with recent input
// commits to surface causal flow on the SectorBoard.
//
// When a light state changes meaningfully, look back ≤2s for the most-
// recent sector "commit" (any input sector whose factors or mode changed)
// and emit a pulse from that input → nucleus → light. Frontend-only
// correlation: imperfect (no backend trigger source), but reads as causal
// for the most common cases (camera commits → light response).

import { writable } from 'svelte/store'

import { lights as lightsStore } from './lights.js'
import { sectorBoard } from './sectorBoard.js'

/** @typedef {{id: string, fromInputId: string, toLightId: string, startedAt: number}} Pulse */

/** @type {import('svelte/store').Writable<Pulse[]>} */
export const pulseLinks = writable([])

const CORRELATION_WINDOW_MS = 2200
const PULSE_DURATION_MS = 1500
const COOLDOWN_MS = 1200 // suppress repeated pulse from same input → same light

// Factor keys that change every minute or so without a real semantic event,
// so we don't want them to act as "commits" that attract correlation.
const COSMETIC_FACTOR_KEYS = new Set(['clock'])

// Minimum change to count as a meaningful light change.
// On/off flips always count.
const MIN_BRI_DELTA = 10
const MIN_HUE_DELTA = 1500
const MIN_SAT_DELTA = 30
const MIN_CT_DELTA = 15

/** @type {Record<string, string>} */
let _lastSectorSig = {}
/** @type {Record<string, number>} */
let _lastInputCommit = {}
/** @type {Record<string, {on:boolean,bri:number,hue:number,sat:number,ct:number}>} */
let _lastLightState = {}
/** @type {Record<string, number>} */
let _lastPulseAt = {}

let _initialized = false
let _readyAt = 0

/**
 * One-time wiring. Subscriptions live for the lifetime of the page; calling
 * twice is a no-op.
 */
export function initPulseLinks() {
  if (_initialized) return
  _initialized = true
  _readyAt = Date.now()

  sectorBoard.subscribe(($sb) => {
    const now = Date.now()
    for (const [id, sector] of Object.entries($sb?.sectors || {})) {
      if (id === 'lights') continue
      const factorSig = (sector?.factors || [])
        .filter((f) => !COSMETIC_FACTOR_KEYS.has(f.key))
        .map((f) => `${f.key}=${f.display}`)
        .join('|')
      const sig = `${sector?.mode || ''}::${factorSig}`
      if (_lastSectorSig[id] !== undefined && _lastSectorSig[id] !== sig) {
        _lastInputCommit[id] = now
      }
      _lastSectorSig[id] = sig
    }
  })

  lightsStore.subscribe(($l) => {
    const now = Date.now()
    // Suppress pulses for the first 1.5s after init — prevents the initial
    // store-population from looking like a flurry of changes.
    if (now - _readyAt < 1500) {
      for (const [id, light] of Object.entries($l || {})) {
        _lastLightState[id] = snapshotLight(light)
      }
      return
    }

    for (const [id, light] of Object.entries($l || {})) {
      const cur = snapshotLight(light)
      const prev = _lastLightState[id]
      _lastLightState[id] = cur
      if (!prev) continue
      if (!isMeaningfulChange(prev, cur)) continue
      const recentInput = mostRecentCommit(now, id)
      if (!recentInput) continue
      firePulse(recentInput, id, now)
    }
  })
}

function snapshotLight(l) {
  return {
    on: !!l?.on,
    bri: l?.bri ?? 0,
    hue: l?.hue ?? 0,
    sat: l?.sat ?? 0,
    ct: l?.ct ?? 0,
  }
}

function isMeaningfulChange(prev, cur) {
  if (prev.on !== cur.on) return true
  // Don't fire pulses on a light that's off — bri changes while off are
  // engine-internal staging, not a visible apartment event.
  if (!cur.on) return false
  if (Math.abs(cur.bri - prev.bri) >= MIN_BRI_DELTA) return true
  if (Math.abs(cur.hue - prev.hue) >= MIN_HUE_DELTA) return true
  if (Math.abs(cur.sat - prev.sat) >= MIN_SAT_DELTA) return true
  if (cur.ct && prev.ct && Math.abs(cur.ct - prev.ct) >= MIN_CT_DELTA) return true
  return false
}

/**
 * Find the input sector that committed most recently, within the correlation
 * window. Returns the sector id or null if nothing qualifies.
 * @param {number} now
 * @param {string} lightId
 */
function mostRecentCommit(now, lightId) {
  let best = null
  let bestAge = Infinity
  for (const [inputId, ts] of Object.entries(_lastInputCommit)) {
    const age = now - ts
    if (age > CORRELATION_WINDOW_MS) continue
    if (age >= bestAge) continue
    // Cooldown — don't fire same input → same light too rapidly.
    const cooldownKey = `${inputId}->${lightId}`
    if ((now - (_lastPulseAt[cooldownKey] || 0)) < COOLDOWN_MS) continue
    best = inputId
    bestAge = age
  }
  return best
}

/**
 * @param {string} fromInputId
 * @param {string} toLightId
 * @param {number} now
 */
function firePulse(fromInputId, toLightId, now) {
  const cooldownKey = `${fromInputId}->${toLightId}`
  _lastPulseAt[cooldownKey] = now
  const pulse = {
    id: `${fromInputId}-${toLightId}-${now}`,
    fromInputId,
    toLightId,
    startedAt: now,
  }
  pulseLinks.update((arr) => [...arr, pulse])
  setTimeout(() => {
    pulseLinks.update((arr) => arr.filter((p) => p.id !== pulse.id))
  }, PULSE_DURATION_MS + 200)
}
