// Camera presence detection state — updated via WebSocket camera_update events.
import { writable } from 'svelte/store'

/** @typedef {{
 *   enabled: boolean,
 *   detection: boolean,
 *   detection_source?: string,
 *   lux?: number,
 *   baseline_lux?: number,
 *   ambient_lux?: number,
 *   ema_lux?: number,
 *   multiplier?: number,
 *   pose_available?: boolean,
 *   zone?: string,
 *   posture?: string,
 *   confidence?: number,
 *   last_detection?: string | null,
 *   calibrated?: boolean,
 *   [key: string]: any
 * }} CameraStatus */

/** @type {import('svelte/store').Writable<CameraStatus | null>} */
export const camera = writable(null)
