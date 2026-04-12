// Design tokens — mode colors, light presets, vibe colors, generative params.
// "Living Ink" redesign: each mode drives generative canvas behavior.

/**
 * @typedef {Object} GenerativeParams
 * @property {number} frequency  - Perlin noise frequency (higher = more turbulent)
 * @property {number} speed      - Time evolution speed
 * @property {number} particleCount - Number of flow-field particles
 * @property {number} trailAlpha - Trail fade per frame (lower = longer trails)
 * @property {number} intensity  - Max particle alpha
 */

/**
 * @typedef {Object} ModeStyle
 * @property {string} label
 * @property {string} lucide    - Lucide icon name
 * @property {string} color
 * @property {GenerativeParams} generative
 */

/** @type {Record<string, ModeStyle>} */
export const MODE_CONFIG = {
  gaming: {
    label: 'Gaming', icon: '🎮', lucide: 'gamepad-2', color: '#a855f7',
    generative: { frequency: 1.2, speed: 0.6, particleCount: 350, trailAlpha: 0.025, intensity: 0.14 },
  },
  working: {
    label: 'Working', icon: '💻', lucide: 'monitor', color: '#3b82f6',
    generative: { frequency: 0.3, speed: 0.1, particleCount: 200, trailAlpha: 0.04, intensity: 0.08 },
  },
  watching: {
    label: 'Watching', icon: '🎬', lucide: 'tv', color: '#8b5cf6',
    generative: { frequency: 0.5, speed: 0.15, particleCount: 250, trailAlpha: 0.03, intensity: 0.10 },
  },
  social: {
    label: 'Social', icon: '🎉', lucide: 'party-popper', color: '#f472b6',
    generative: { frequency: 0.9, speed: 0.8, particleCount: 400, trailAlpha: 0.02, intensity: 0.15 },
  },
  relax: {
    label: 'Relax', icon: '🌙', lucide: 'flame', color: '#fb923c',
    generative: { frequency: 0.5, speed: 0.2, particleCount: 250, trailAlpha: 0.03, intensity: 0.10 },
  },
  movie: {
    label: 'Movie', icon: '🎥', lucide: 'clapperboard', color: '#6366f1',
    generative: { frequency: 0.5, speed: 0.15, particleCount: 250, trailAlpha: 0.03, intensity: 0.10 },
  },
  sleeping: {
    label: 'Sleeping', icon: '😴', lucide: 'moon', color: '#1e3a8a',
    generative: { frequency: 0.15, speed: 0.05, particleCount: 150, trailAlpha: 0.05, intensity: 0.06 },
  },
  idle: {
    label: 'Idle', icon: '✨', lucide: 'sparkles', color: '#6b7280',
    generative: { frequency: 0.2, speed: 0.08, particleCount: 100, trailAlpha: 0.04, intensity: 0.06 },
  },
  away: {
    label: 'Away', icon: '🚪', lucide: 'door-open', color: '#475569',
    generative: { frequency: 0.1, speed: 0.0, particleCount: 80, trailAlpha: 0.05, intensity: 0.04 },
  },
  auto: {
    label: 'Auto', icon: '🤖', lucide: 'bot', color: '#4a6cf7',
    generative: { frequency: 0.4, speed: 0.15, particleCount: 200, trailAlpha: 0.03, intensity: 0.08 },
  },
}

/** @type {Array<{ name: string, hue: number, sat: number }>} */
export const LIGHT_COLOR_PRESETS = [
  { name: 'warm',   hue: 8000,  sat: 180 },
  { name: 'cool',   hue: 40000, sat: 120 },
  { name: 'red',    hue: 0,     sat: 254 },
  { name: 'orange', hue: 5000,  sat: 254 },
  { name: 'yellow', hue: 12750, sat: 254 },
  { name: 'green',  hue: 25500, sat: 254 },
  { name: 'blue',   hue: 46920, sat: 254 },
  { name: 'purple', hue: 56100, sat: 254 },
]

/** @type {Array<{ name: string, ct: number, label: string }>} */
export const LIGHT_CT_PRESETS = [
  { name: 'candle',   ct: 500, label: '2000K' },
  { name: 'warm',     ct: 370, label: '2700K' },
  { name: 'neutral',  ct: 250, label: '4000K' },
  { name: 'cool',     ct: 182, label: '5500K' },
  { name: 'daylight', ct: 153, label: '6500K' },
]

/** @type {Record<string, { label: string, color: string }>} */
export const SCENE_CATEGORIES = {
  functional:    { label: 'Functional',    color: '#3b82f6' },
  cozy:          { label: 'Cozy',          color: '#fb923c' },
  moody:         { label: 'Moody',         color: '#6366f1' },
  vibrant:       { label: 'Vibrant',       color: '#f43f5e' },
  nature:        { label: 'Nature',        color: '#34d399' },
  entertainment: { label: 'Entertainment', color: '#8b5cf6' },
  social:        { label: 'Social',        color: '#f472b6' },
  custom:        { label: 'Custom',        color: '#a855f7' },
}

/** @type {Record<string, string>} */
export const VIBE_COLORS = {
  energetic:  '#f472b6',
  focus:      '#3b82f6',
  mellow:     '#8b5cf6',
  background: '#6b7280',
  hype:       '#f87171',
}

/** @type {Array<{ id: string, label: string, icon: string }>} */
export const SOCIAL_STYLES = [
  { id: 'color_cycle',   label: 'Color Cycle',   icon: '🌈' },
  { id: 'club',          label: 'Club',          icon: '💃' },
  { id: 'rave',          label: 'Rave',          icon: '⚡' },
  { id: 'fire_and_ice',  label: 'Fire & Ice',    icon: '❄️' },
]

export function modeColor(mode) {
  return MODE_CONFIG[mode]?.color ?? MODE_CONFIG.idle.color
}

export function modeLabel(mode) {
  return MODE_CONFIG[mode]?.label ?? mode
}

export function modeLucide(mode) {
  return MODE_CONFIG[mode]?.lucide ?? 'sparkles'
}

export function modeGenerative(mode) {
  return MODE_CONFIG[mode]?.generative ?? MODE_CONFIG.idle.generative
}
