/**
 * Per-mode layer configurations for the ParallaxScene.
 *
 * Each mode defines an array of layers rendered back-to-front.
 * Layers reference PNGs in /static/backgrounds/{mode}/.
 *
 * duration: seconds for one full horizontal scroll (lower = faster).
 *           0 = static (no scroll).
 * opacity: base opacity (0-1).
 * zIndex: stacking order (higher = in front).
 */

/** @typedef {{src: string, duration: number, opacity: number, zIndex: number}} LayerDef */

/** @type {Record<string, LayerDef[]>} */
export const LAYER_CONFIGS = {
  working: [
    { src: '/backgrounds/working/sky.png',            duration: 0,   opacity: 1,   zIndex: 0 },
    { src: '/backgrounds/working/buildings-far.png',   duration: 120, opacity: 1,   zIndex: 1 },
    { src: '/backgrounds/working/buildings-near.png',  duration: 60,  opacity: 1,   zIndex: 2 },
    { src: '/backgrounds/working/street.png',          duration: 30,  opacity: 1,   zIndex: 3 },
  ],
  // Future modes: just add entries here with their layer PNGs
  // gaming: [ ... ],
  // relax: [ ... ],
}

/**
 * Get sky variant based on time of day and weather.
 * @param {string} mode
 * @param {string} weather - weather description from API
 * @returns {string} sky image path
 */
export function getSkyVariant(mode, weather = 'clear') {
  if (mode !== 'working') return LAYER_CONFIGS[mode]?.[0]?.src || ''

  const hour = new Date().getHours()
  const base = '/backgrounds/working'

  // Check if variant files exist by trying them — fallback to default sky
  if (weather.includes('overcast') || weather.includes('cloud')) {
    return `${base}/sky-overcast.png`
  }
  if (hour >= 17 && hour < 20) return `${base}/sky-sunset.png`
  if (hour >= 20 || hour < 6) return `${base}/sky-night.png`
  return `${base}/sky.png`
}

/** Music speed multiplier per mode */
export const MUSIC_SPEED_BOOST = {
  working: 0.7, // durations multiplied by this when music plays (lower = faster)
  gaming: 0.6,
  relax: 0.85,
}
