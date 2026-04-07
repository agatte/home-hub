import { writable } from 'svelte/store'

/** @type {import('svelte/store').Writable<boolean>} */
export const connected = writable(false)

/**
 * @typedef {Object} DeviceStatus
 * @property {boolean} hue
 * @property {boolean} sonos
 */

/** @type {import('svelte/store').Writable<DeviceStatus>} */
export const deviceStatus = writable({ hue: false, sonos: false })
