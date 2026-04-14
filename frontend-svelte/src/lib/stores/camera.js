// Camera presence detection state — updated via WebSocket camera_update events.
import { writable } from 'svelte/store'

export const camera = writable(null)
