import { beforeEach, describe, expect, it } from 'vitest'
import { get } from 'svelte/store'

import {
  lights,
  applyLightUpdate,
  setLightsFromList,
  optimisticLightPatch,
} from '$lib/stores/lights.js'

beforeEach(() => {
  lights.set({})
})

describe('applyLightUpdate', () => {
  it('adds a new light keyed by light_id', () => {
    applyLightUpdate({ light_id: '1', name: 'Hall', on: true, bri: 200, hue: 0, sat: 0, reachable: true })
    expect(get(lights)['1'].name).toBe('Hall')
  })

  it('replaces an existing light entry', () => {
    applyLightUpdate({ light_id: '1', name: 'Hall', on: true, bri: 100, hue: 0, sat: 0, reachable: true })
    applyLightUpdate({ light_id: '1', name: 'Hall', on: false, bri: 0, hue: 0, sat: 0, reachable: true })
    expect(get(lights)['1'].on).toBe(false)
    expect(get(lights)['1'].bri).toBe(0)
  })
})

describe('setLightsFromList', () => {
  it('replaces the full map keyed by light_id', () => {
    setLightsFromList([
      { light_id: '1', name: 'A', on: true, bri: 200, hue: 0, sat: 0, reachable: true },
      { light_id: '2', name: 'B', on: false, bri: 0, hue: 0, sat: 0, reachable: true },
    ])
    const map = get(lights)
    expect(Object.keys(map).sort()).toEqual(['1', '2'])
    expect(map['2'].name).toBe('B')
  })

  it('overwrites prior state', () => {
    applyLightUpdate({ light_id: '1', name: 'old', on: true, bri: 200, hue: 0, sat: 0, reachable: true })
    setLightsFromList([])
    expect(get(lights)).toEqual({})
  })
})

describe('optimisticLightPatch', () => {
  it('merges a partial patch onto an existing light', () => {
    applyLightUpdate({ light_id: '1', name: 'Hall', on: true, bri: 100, hue: 0, sat: 0, reachable: true })
    optimisticLightPatch('1', { bri: 250 })
    const light = get(lights)['1']
    expect(light.bri).toBe(250)
    expect(light.name).toBe('Hall')
  })
})
