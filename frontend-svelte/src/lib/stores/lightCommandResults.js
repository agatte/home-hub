import { writable } from 'svelte/store'
import { automation } from './automation.js'
import { createLightCommandReceiptTracker } from '$lib/quietAtlas/lightCommandReceiptTracker.js'

/** @type {import('svelte/store').Writable<Record<string, { status: string, commandId: string | null }>>} */
export const lightCommandResults = writable({})

export const lightCommandTracker = createLightCommandReceiptTracker({
  onUpdate: (snapshot) => lightCommandResults.set(snapshot),
})

// Both REST and live WebSocket reports update the same authoritative store.
automation.subscribe(state => lightCommandTracker.observeModeContext(state))
