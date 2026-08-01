/**
 * Per-mode layer configurations for the ParallaxScene.
 *
 * Each mode defines an array of layers rendered back-to-front.
 * Layers reference PNGs in /static/backgrounds/{mode}/.
 *
 * duration: seconds for one full scroll cycle (lower = faster). 0 = static.
 * opacity: base opacity (0-1).
 * zIndex: stacking order (higher = in front).
 * sizing: 'cover' stretches to fill, 'tile' repeats horizontally for scrolling.
 * anchor: 'bottom' pins layer to bottom of viewport, 'full' fills viewport.
 * height: optional — CSS height if layer should only cover a portion (e.g. '40%').
 */

/** @typedef {{src: string, duration: number, opacity: number, zIndex: number, sizing?: string, anchor?: string, height?: string}} LayerDef */

/** @type {Record<string, LayerDef[]>} */
export const LAYER_CONFIGS = {
  working: [
    // Single street scene — has buildings, streetlamps, characters baked in.
    // Fills lower 75% with a code-drawn sky gradient above.
    { src: '/backgrounds/working/street.png', duration: 40, opacity: 1, zIndex: 1,
      sizing: 'tile', anchor: 'bottom', height: '75%' },
  ],
}

/** Music speed multiplier per mode (applied to durations — lower = faster) */
export const MUSIC_SPEED_BOOST = {
  working: 0.7,
  gaming: 0.6,
  relax: 0.85,
}
