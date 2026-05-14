// Trailing-debounce wrapper for Svelte stores. Same shape as `derived`
// (single store or array), but coalesces bursts of upstream updates into
// at most one downstream emit per `ms` window.
//
// Initial value is emitted synchronously on first subscribe so consumers
// don't see undefined before the first debounce window elapses.

import { readable } from 'svelte/store'

/**
 * @template T
 * @param {import('svelte/store').Readable<any> | Array<import('svelte/store').Readable<any>>} stores
 * @param {(values: any) => T} fn
 * @param {number} [ms=150]
 * @returns {import('svelte/store').Readable<T>}
 */
export function debounced(stores, fn, ms = 150) {
  const inputs = Array.isArray(stores) ? stores : [stores]
  const single = !Array.isArray(stores)

  return readable(/** @type {T} */ (/** @type {unknown} */ (undefined)), (set) => {
    /** @type {ReturnType<typeof setTimeout> | null} */
    let timer = null
    let initialized = false
    const values = new Array(inputs.length)

    function compute() {
      return fn(single ? values[0] : values)
    }

    function scheduleEmit() {
      // During the initial subscribe-fan-out, multiple stores fire their
      // current value back synchronously. Wait until all inputs are seeded
      // before debouncing — the post-init `set(compute())` below covers
      // the first emit.
      if (!initialized) return
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        set(compute())
      }, ms)
    }

    const unsubs = inputs.map((store, i) =>
      store.subscribe((v) => {
        values[i] = v
        scheduleEmit()
      }),
    )

    initialized = true
    set(compute())

    return () => {
      if (timer) clearTimeout(timer)
      unsubs.forEach((u) => u())
    }
  })
}
