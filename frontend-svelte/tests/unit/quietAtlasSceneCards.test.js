import { describe, expect, it } from 'vitest'
import { sceneCards, scenePalette, sceneCardBackground, sceneTemperatureColor, sceneBackgroundForId } from '../../src/lib/quietAtlas/sceneCards.js'

const preset = { id: 'deep_focus', display_name: 'Deep Focus', source: 'preset', category: 'functional', lights: {
  '1': { on: true, ct: 250 }, '2': { on: true, ct: 250 }, '3': { on: false, hue: 60000, sat: 254 },
  '4': { on: true, hue: 45000, sat: 200 }, '5': { on: true, ct: 'invalid' }
} }
const hue = (id, group_id) => ({ id, group_id, name: 'Ocean dawn', source: 'bridge' })

describe('Scene library presentation', () => {
  it('uses only valid, enabled saved fixture colors and removes repeats', () => {
    expect(scenePalette(preset)).toEqual([sceneTemperatureColor(250), `hsl(${45000 / 65535 * 360}, ${200 / 254 * 100}%, 62%)`])
    expect(sceneCardBackground(scenePalette(preset))).toContain(sceneTemperatureColor(250))
    expect(sceneCardBackground(scenePalette(preset))).toContain(`hsl(${45000 / 65535 * 360}, ${200 / 254 * 100}%, 62%)`)
    expect(scenePalette(hue('scene-a', 'group-a'))).toEqual([])
    expect(sceneCardBackground([])).toBe('')
  })
  it('uses naturally warmer white temperatures and one shared shortcut gradient', () => {
    const rgb = mirek => (sceneTemperatureColor(mirek).match(/\d+/g) ?? []).map(Number)
    const cool = rgb(153), warm = rgb(500)
    expect(warm[0]).toBeGreaterThanOrEqual(warm[1])
    expect(warm[2]).toBeLessThan(cool[2])
    expect(rgb(250)[1]).toBeGreaterThan(rgb(250)[2])
    expect(sceneBackgroundForId([preset], preset.id)).toBe(sceneCardBackground(scenePalette(preset)))
    expect(sceneBackgroundForId([preset], 'unknown')).toBe('')
  })
  it('groups Hue duplicate names but retains each independent target ID', () => {
    const cards = sceneCards([preset, hue('scene-a', 'group-a'), hue('scene-b', 'group-b')])
    expect(cards).toHaveLength(2)
    expect(cards[1].variants.map(v => v.id)).toEqual(['scene-a', 'scene-b'])
    expect(cards[1].variants[0].label).not.toEqual(cards[1].variants[1].label)
    expect(sceneCards([preset, hue('scene-a', 'group-a')], { search: 'Ocean', category: 'bridge' })).toHaveLength(1)
  })
  it('does not collapse custom or curated scenes merely because names match', () => {
    const rows = [preset, { ...preset, id: 'other', source: 'custom' }, { ...preset, id: 'another' }]
    expect(sceneCards(rows).map(c => c.id)).toEqual(['deep_focus', 'other', 'another'])
  })
})
