import { describe, it, expect } from 'vitest'
import {
  LIGHTING_GROUPS,
  brightnessPercent,
  describeFixture,
  summarizeFixtureGroup,
  buildLightingOverview,
  normalizeSceneList,
  selectQuickScenes,
  filterScenes,
  fixtureStatusLabel,
} from '../../src/lib/quietAtlas/lightingModel.js'

const light = (id, on, bri = 127, reachable = true) => ({
  light_id: id, name: `Fixture ${id}`, on, bri, reachable,
})

describe('Quiet Atlas read-only lighting projection (#270)', () => {
  it('uses the actual fixture map without inventing writable groups', () => {
    expect(LIGHTING_GROUPS.map(({ id, lightIds }) => [id, lightIds])).toEqual([
      ['living', ['1']], ['bedroom', ['2', '5']],
      ['kitchen', ['3', '4']], ['plant', ['6']],
    ])
    const groups = buildLightingOverview({ '2': light('2', true), '5': light('5', false), '3': light('3', true), '4': light('4', false) })
    expect(groups.find(({ id }) => id === 'bedroom').status).toBe('mixed')
    expect(groups.find(({ id }) => id === 'kitchen').status).toBe('mixed')
    expect(groups.every(({ supportsGroupWrite }) => supportsGroupWrite === false)).toBe(true)
  })

  it('separates missing, unknown reachability, and explicitly offline', () => {
    expect(buildLightingOverview({}).map(({ status }) => status)).toEqual(['unknown', 'unknown', 'unknown', 'unknown'])
    expect(describeFixture({ light_id: '1', on: true }, '1').reachable).toBeNull()
    expect(describeFixture({ light_id: '1', on: true }, '1').on).toBeNull()
    expect(summarizeFixtureGroup([describeFixture({ reachable: false }, '6')])).toBe('offline')
    expect(fixtureStatusLabel(describeFixture({ reachable: true }, '1'))).toBe('State unavailable')
  })

  it('treats cached states as stale during disconnection', () => {
    const groups = buildLightingOverview({ '1': light('1', true) }, false)
    expect(groups.every(({ status }) => status === 'stale')).toBe(true)
    expect(groups[0].fixtures[0].on).toBe(true)
  })

  it('keeps the individual bedroom brightness levels separate', () => {
    const source = { '2': light('2', true, 254), '5': light('5', false, 25) }
    const bedroom = buildLightingOverview(source).find(({ id }) => id === 'bedroom')
    expect(bedroom.fixtures.map(({ on }) => on)).toEqual([true, false])
    expect(bedroom.fixtures.map(({ brightness }) => brightness)).toEqual([100, null])
    expect(source['2'].bri).toBe(254)
    expect(brightnessPercent(0)).toBeNull()
    expect(brightnessPercent(255)).toBeNull()
    expect(brightnessPercent(NaN)).toBeNull()
  })

  it('places unknown newly discovered fixtures into read-only Other lights', () => {
    const groups = buildLightingOverview({ '6': light('6', false), '12': light('12', true) })
    expect(groups.find(({ id }) => id === 'plant').status).toBe('off')
    expect(groups.at(-1).fixtureIds).toEqual(['12'])
    expect(groups.at(-1).supportsGroupWrite).toBe(false)
  })

  it('takes quick scenes only from the API, never from invented selections', () => {
    const api = [
      { id: 'golden_hour', display_name: 'Golden Hour', source: 'preset', category: 'cozy' },
      { id: 'movie_night', display_name: 'Movie Night', source: 'preset', category: 'entertainment' },
      { id: 'custom_5', display_name: 'My Scene', source: 'custom', category: 'custom' },
      { id: 'bridge_4', name: 'Hue Sunset', source: 'bridge' },
      { id: 'bad', name: 'Untrusted', source: 'other' },
      { id: 'golden_hour', display_name: 'Duplicate', source: 'preset' },
    ]
    expect(normalizeSceneList(api).map(({ id }) => id)).toEqual(['golden_hour', 'movie_night', 'custom_5', 'bridge_4'])
    expect(selectQuickScenes(api).map(({ id }) => id)).toEqual(['golden_hour', 'movie_night'])
    expect(selectQuickScenes(api, ['custom_5', 'missing']).map(({ id }) => id)).toEqual(['custom_5'])
    expect(selectQuickScenes([])).toEqual([])
  })

  it('filters scenes by source/category and case-insensitive query', () => {
    const api = [
      { id: 'e', display_name: 'Ember', source: 'preset', category: 'cozy' },
      { id: 'c', display_name: 'Custom Ember', source: 'custom', category: 'social' },
      { id: 'b', display_name: 'Bridge Ember', source: 'bridge' },
    ]
    expect(filterScenes(api, { category: 'cozy' }).map(({ id }) => id)).toEqual(['e'])
    expect(filterScenes(api, { category: 'bridge', search: 'eMbEr' }).map(({ id }) => id)).toEqual(['b'])
    expect(filterScenes(api, { search: 'ember' }).map(({ id }) => id)).toEqual(['e', 'c', 'b'])
  })

  it('does not fabricate a level when an on light lacks valid brightness', () => {
    expect(fixtureStatusLabel(describeFixture({ reachable: true, on: true }, '1'))).toBe('On · brightness unknown')
    expect(fixtureStatusLabel(describeFixture(undefined, '1'))).toBe('Unknown')
    expect(fixtureStatusLabel(describeFixture({ reachable: false, on: false }, '1'))).toBe('Offline')
  })
})
