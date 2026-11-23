import { writable } from 'svelte/store'
import { createLightCommandReceiptTracker } from '$lib/quietAtlas/lightCommandReceiptTracker.js'

/** @type {import('svelte/store').Writable<Record<string, { status: string, commandId: string | null }>>} */
export const lightCommandResults = writable({})

export const lightCommandTracker = createLightCommandReceiptTracker({
  onUpdate: (snapshot) => lightCommandResults.set(snapshot),
})
