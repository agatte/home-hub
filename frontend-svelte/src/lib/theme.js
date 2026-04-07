// Design tokens — single source for mode colors, light presets, vibe colors.
// The React codebase scatters these across ModeIndicator.jsx, LightCard.jsx,
// ModeOverrideBar.jsx, etc. Centralizing them in the Svelte rewrite kills one
// of the "feels generic" complaints from docs/PROJECT_SPEC.md without doing a
// full visual refresh. Keep visual values 1:1 with the React app for parity.

/**
 * @typedef {Object} ModeStyle
 * @property {string} label
 * @property {string} icon
 * @property {string} color
 */

/** @type {Record<string, ModeStyle>} */
export const MODE_CONFIG = {
  gaming:   { label: 'Gaming',   icon: '🎮', color: '#a855f7' },
  working:  { label: 'Working',  icon: '💻', color: '#3b82f6' },
  watching: { label: 'Watching', icon: '🎬', color: '#8b5cf6' },
  social:   { label: 'Social',   icon: '🎉', color: '#f472b6' },
  relax:    { label: 'Relax',    icon: '🌙', color: '#fb923c' },
  movie:    { label: 'Movie',    icon: '🎥', color: '#6366f1' },
  sleeping: { label: 'Sleeping', icon: '😴', color: '#1e3a8a' },
  idle:     { label: 'Idle',     icon: '✨', color: '#6b7280' },
  away:     { label: 'Away',     icon: '🚪', color: '#475569' },
  auto:     { label: 'Auto',     icon: '🤖', color: '#4a6cf7' },
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

export function modeIcon(mode) {
  return MODE_CONFIG[mode]?.icon ?? '✨'
}
