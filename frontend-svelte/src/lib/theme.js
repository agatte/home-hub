// Design tokens — mode colors, light presets, vibe colors, generative params.
// "Living Ink" redesign: each mode drives generative canvas behavior.

/**
 * @typedef {Object} GenerativeParams
 * @property {number} blobCount      - Gradient mesh blobs (2-4)
 * @property {number} blobOpacity    - Max blob opacity (0.05-0.25)
 * @property {number} blobSpeed      - Blob drift speed
 * @property {number} particleCount  - Flow-field particle count
 * @property {number} particleSize   - Particle radius in px
 * @property {number} particleSpeed  - Particle flow speed
 * @property {number} particleTrail  - Trail fade per frame (lower = longer)
 * @property {number} particleIntensity - Max particle alpha
 * @property {string} particleStyle  - 'dots' | 'streaks' | 'embers' | 'none'
 * @property {string} geoPattern     - 'none' | 'grid' | 'hex' | 'waves' | 'rings' | 'radial'
 * @property {number} geoOpacity     - Geometric overlay opacity
 * @property {number} musicBlobPulse - Blob scale delta when music plays
 * @property {number} musicSpeedBoost - Particle speed multiplier when music plays
 * @property {number} noiseFrequency - Perlin noise frequency
 * @property {string} [secondaryColor] - Fallback secondary color hex
 * @property {string} [accentColor]    - Fallback accent color hex
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
    generative: {
      blobCount: 4, blobOpacity: 0.20, blobSpeed: 0.5,
      particleCount: 200, particleSize: 4, particleSpeed: 0.6,
      particleTrail: 0.02, particleIntensity: 0.4, particleStyle: 'streaks',
      geoPattern: 'hex', geoOpacity: 0.05,
      musicBlobPulse: 0.18, musicSpeedBoost: 1.5, noiseFrequency: 1.0,
      secondaryColor: '#7c3aed', accentColor: '#c084fc',
    },
  },
  working: {
    label: 'Working', icon: '💻', lucide: 'monitor', color: '#3b82f6',
    generative: {
      blobCount: 2, blobOpacity: 0.10, blobSpeed: 0.15,
      particleCount: 80, particleSize: 2, particleSpeed: 0.12,
      particleTrail: 0.04, particleIntensity: 0.25, particleStyle: 'dots',
      geoPattern: 'grid', geoOpacity: 0.03,
      musicBlobPulse: 0.08, musicSpeedBoost: 1.2, noiseFrequency: 0.3,
      secondaryColor: '#1d4ed8', accentColor: '#60a5fa',
    },
  },
  watching: {
    label: 'Watching', icon: '🎬', lucide: 'tv', color: '#8b5cf6',
    generative: {
      blobCount: 2, blobOpacity: 0.06, blobSpeed: 0.1,
      particleCount: 20, particleSize: 2, particleSpeed: 0.08,
      particleTrail: 0.05, particleIntensity: 0.15, particleStyle: 'dots',
      geoPattern: 'none', geoOpacity: 0,
      musicBlobPulse: 0, musicSpeedBoost: 1.0, noiseFrequency: 0.2,
      secondaryColor: '#6d28d9',
    },
  },
  social: {
    label: 'Social', icon: '🎉', lucide: 'party-popper', color: '#f472b6',
    generative: {
      blobCount: 4, blobOpacity: 0.22, blobSpeed: 0.6,
      particleCount: 250, particleSize: 3, particleSpeed: 0.7,
      particleTrail: 0.018, particleIntensity: 0.45, particleStyle: 'dots',
      geoPattern: 'radial', geoOpacity: 0.06,
      musicBlobPulse: 0.20, musicSpeedBoost: 1.6, noiseFrequency: 0.8,
      secondaryColor: '#ec4899', accentColor: '#a855f7',
    },
  },
  relax: {
    label: 'Relax', icon: '🌙', lucide: 'flame', color: '#fb923c',
    generative: {
      blobCount: 3, blobOpacity: 0.15, blobSpeed: 0.2,
      particleCount: 100, particleSize: 3, particleSpeed: 0.15,
      particleTrail: 0.03, particleIntensity: 0.3, particleStyle: 'embers',
      geoPattern: 'waves', geoOpacity: 0.04,
      musicBlobPulse: 0.12, musicSpeedBoost: 1.3, noiseFrequency: 0.4,
      secondaryColor: '#f97316', accentColor: '#fdba74',
    },
  },
  cooking: {
    label: 'Cooking', icon: '🍳', lucide: 'chef-hat', color: '#f59e0b',
    generative: {
      blobCount: 3, blobOpacity: 0.18, blobSpeed: 0.3,
      particleCount: 60, particleSize: 3, particleSpeed: 0.2,
      particleTrail: 0.04, particleIntensity: 0.3, particleStyle: 'embers',
      geoPattern: 'grid', geoOpacity: 0.05,
      musicBlobPulse: 0.1, musicSpeedBoost: 1.2, noiseFrequency: 0.5,
      secondaryColor: '#ea580c', accentColor: '#fed7aa',
    },
  },
  sleeping: {
    label: 'Sleeping', icon: '😴', lucide: 'moon', color: '#1e3a8a',
    generative: {
      blobCount: 1, blobOpacity: 0.04, blobSpeed: 0.05,
      particleCount: 30, particleSize: 2, particleSpeed: 0.03,
      particleTrail: 0.06, particleIntensity: 0.1, particleStyle: 'dots',
      geoPattern: 'none', geoOpacity: 0,
      musicBlobPulse: 0, musicSpeedBoost: 1.0, noiseFrequency: 0.1,
      secondaryColor: '#1e1b4b',
    },
  },
  idle: {
    label: 'Idle', icon: '✨', lucide: 'sparkles', color: '#6b7280',
    generative: {
      blobCount: 2, blobOpacity: 0.08, blobSpeed: 0.12,
      particleCount: 60, particleSize: 2, particleSpeed: 0.08,
      particleTrail: 0.04, particleIntensity: 0.2, particleStyle: 'dots',
      geoPattern: 'rings', geoOpacity: 0.03,
      musicBlobPulse: 0.10, musicSpeedBoost: 1.3, noiseFrequency: 0.2,
      secondaryColor: '#4b5563', accentColor: '#374151',
    },
  },
  away: {
    label: 'Away', icon: '🚪', lucide: 'door-open', color: '#475569',
    generative: {
      blobCount: 1, blobOpacity: 0.05, blobSpeed: 0.02,
      particleCount: 40, particleSize: 2, particleSpeed: 0.02,
      particleTrail: 0.06, particleIntensity: 0.1, particleStyle: 'dots',
      geoPattern: 'none', geoOpacity: 0,
      musicBlobPulse: 0, musicSpeedBoost: 1.0, noiseFrequency: 0.1,
      secondaryColor: '#334155',
    },
  },
  auto: {
    label: 'Auto', icon: '🤖', lucide: 'bot', color: '#4a6cf7',
    generative: {
      blobCount: 2, blobOpacity: 0.08, blobSpeed: 0.15,
      particleCount: 80, particleSize: 2, particleSpeed: 0.1,
      particleTrail: 0.04, particleIntensity: 0.2, particleStyle: 'dots',
      geoPattern: 'none', geoOpacity: 0,
      musicBlobPulse: 0.08, musicSpeedBoost: 1.2, noiseFrequency: 0.3,
      secondaryColor: '#3b5ce0',
    },
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
