import { writable } from 'svelte/store'

/** @type {import('svelte/store').Writable<Array<{id: number, message: string}>>} */
export const errors = writable([])

let nextId = 0

/** @param {string} message */
export function addError(message) {
  const id = nextId++
  errors.update((list) => [...list, { id, message }])
  setTimeout(() => {
    errors.update((list) => list.filter((e) => e.id !== id))
  }, 5000)
}
