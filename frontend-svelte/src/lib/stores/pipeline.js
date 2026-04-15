// Decision pipeline store — real-time snapshot of all automation inputs,
// priority resolution, and final output state.

import { writable } from 'svelte/store'

/** @type {import('svelte/store').Writable<{ current: any, history: any[] }>} */
export const pipeline = writable({
  current: null,
  history: [],
})
