// Presence state — phone on/off home WiFi. Initialized via REST on app
// mount and live-updated via WS `presence_update` events.
//
// Shape matches `PresenceService.get_status()`:
//   { state, enabled, phone_ip, last_seen, away_since, away_duration_minutes }

import { writable } from 'svelte/store'

/** @type {import('svelte/store').Writable<{
 *   state: string,
 *   enabled?: boolean,
 *   phone_ip?: string,
 *   last_seen?: string | null,
 *   away_since?: string | null,
 *   away_duration_minutes?: number | null,
 * }>} */
export const presence = writable({ state: 'unknown' })
