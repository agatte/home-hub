// Camera presence detection state — updated via WebSocket camera_update events.
import { writable } from 'svelte/store'

/** @typedef {{
 *   enabled: boolean,
 *   detection?: string,
 *   detection_source?: string,
 *   lux?: number,
 *   baseline_lux?: number,
 *   ambient_lux?: number,
 *   ema_lux?: number,
 *   multiplier?: number,
 *   current_multiplier?: number,
 *   pose_available?: boolean,
 *   zone?: string,
 *   posture?: string,
 *   confidence?: number,
 *   last_detection?: string | null,
 *   calibrated?: boolean,
 *   calibrating?: boolean,
 *   paused?: boolean,
 *   exposure_value?: number,
 *   [key: string]: any
 * }} CameraStatus */

/** @type {import('svelte/store').Writable<CameraStatus | null>} */
export const camera = writable(null)
