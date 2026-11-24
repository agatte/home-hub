import { describe, expect, it } from 'vitest'
import { sceneCards, scenePalette, sceneCardBackground } from '../../src/lib/quietAtlas/sceneCards.js'
import { ctToColor, hueToHsl } from '../../src/lib/utils/lightColor.js'

const preset = { id: 'deep_focus', display_name: 'Deep Focus', source: 'preset', category: 'functional', lights: {
  '1': { on: true, ct: 250 }, '2': { on: true, ct: 250 }, '3': { on: false, hue: 60000, sat: 254 },
  '4': { on: true, hue: 45000, sat: 200 }, '5': { on: true, ct: 'invalid' }
} }
const hue = (id, group_id) => ({ id, group_id, name: 'Ocean dawn', source: 'bridge' })

describe('Scene library presentation', () => {
  it('uses only valid, enabled saved fixture colors and removes repeats', () => {
    expect(scenePalette(preset)).toEqual([ctToColor(250), hueToHsl(45000, 200, 220)])
    expect(sceneCardBackground(scenePalette(preset))).toContain(ctToColor(250))
    expect(sceneCardBackground(scenePalette(preset))).toContain(hueToHsl(45000, 200, 220))
    expect(scenePalette(hue('scene-a', 'group-a'))).toEqual([])
    expect(sceneCardBackground([])).toBe('')
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
