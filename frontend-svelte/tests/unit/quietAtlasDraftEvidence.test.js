import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { tick } from 'svelte'
import { compile } from 'svelte/compiler'
import { describeFixture, buildLightingOverview } from '../../src/lib/quietAtlas/lightingModel.js'
import { fixtureDraftEvidence } from '../../src/lib/quietAtlas/controlDraft.js'
import GroupSheet from '../../src/lib/components/QuietAtlasGroupSheet.svelte'
import sheet from '../../src/lib/components/QuietAtlasGroupSheet.svelte?raw'
import experience from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'

const raw = {
  light_id: '2', name: 'Shaded desk lamp', reachable: true, on: true,
  bri: 178, ct: 350, colormode: 'ct',
}
const identity = (state = raw, id = '2') => fixtureDraftEvidence(describeFixture(state, id), state)

describe('Quiet Atlas local brightness review freshness (#461)', () => {
  it('retains local review only across identical reported fixture evidence', () => {
    expect(identity()).toBeTypeOf('string')
    expect(identity({ ...raw })).toBe(identity())
    expect(identity({ ...raw, other_metadata: 'poll-2' })).toBe(identity())
  })

  it('revokes drafts on any materially changed reported fixture or identity', () => {
    for (const variant of [
      { name: 'Another fixture' }, { bri: 179 }, { ct: 351 },
      { colormode: 'hs' }, { sat: 10 }, { hue: 12000 },
      { effect: 'colorloop' }, { alert: 'select' },
      { on: false }, { reachable: false }, { light_id: '5' },
    ]) {
      const changed = { ...raw, ...variant }
      expect(identity(changed)).not.toBe(identity())
    }
    expect(identity(raw, '5')).toBeNull()
    expect(identity({ ...raw, on: false })).toBeNull()
    expect(identity({ ...raw, reachable: false })).toBeNull()
    expect(fixtureDraftEvidence(undefined, raw)).toBeNull()
    expect(fixtureDraftEvidence(describeFixture(raw, '2'), null)).toBeNull()
  })

  it('reconciles draft evidence only on this read-only sheet and keeps all writers absent', () => {
    expect(experience).toContain('fixtureStates={snapshot.fixtures}')
    expect(sheet).toContain('export let fixtureStates = {}')
    expect(sheet).toContain('Object.entries(draftEvidence).some')
    expect(sheet).toContain('fixtureDraftEvidence(group.fixtures.find')
    expect(sheet).toContain('reviewHasFocus()')
    expect(sheet).toContain('restoreReviewFocus(id)')
    expect(sheet).toContain('draftEvidence = {}')
    expect(sheet).toContain("snapshotStatus !== 'recent-read'")
    expect(sheet).toContain('if (snapshotStatus !== \'recent-read\' || evidence === null) return')
    expect(sheet).toContain('Nothing is sent to HomeHub')
    for (const source of [sheet, experience]) {
      expect(source).not.toMatch(/\b(apiPost|apiPut|setLight|activateScene)\s*\(/)
    }
    for (const [filename, source] of [
      ['QuietAtlasGroupSheet.svelte', sheet],
      ['QuietAtlasLightingExperience.svelte', experience],
    ]) {
      expect(compile(source, { filename, generate: 'dom', css: 'external' }).warnings).toEqual([])
    }
  })
})

const livingStates = (overrides = {}) => ({
  '2': { ...raw, ...overrides },
  '5': { light_id: '5', name: 'Clear lamp', reachable: true, on: true, bri: 80, ct: 400 },
})
const bedroom = (states) => buildLightingOverview(states, true).find((group) => group.id === 'bedroom')

async function openBedroomReview() {
  const slider = screen.getByRole('slider', { name: /Draft Shaded desk lamp brightness percentage/ })
  await fireEvent.input(slider, { target: { value: '75' } })
  const action = document.querySelector('button.review[data-fixture-id="2"]')
  expect(action).toBeInstanceOf(HTMLButtonElement)
  if (!(action instanceof HTMLButtonElement)) throw new Error('Fixture review control missing')
  expect(action.disabled).toBe(false)
  await fireEvent.click(action)
  await tick()
  const dismiss = screen.getByRole('button', { name: 'Dismiss review' })
  dismiss.focus()
  expect(document.activeElement).toBe(dismiss)
  return dismiss
}

describe('mounted read-only fixture draft reconciliation (#461)', () => {
  it('keeps an actively reviewed draft through an identical routine status read', async () => {
    const initial = livingStates()
    const { rerender } = render(GroupSheet, {
      group: bedroom(initial), snapshotStatus: 'recent-read', fixtureStates: initial,
    })
    await openBedroomReview()
    const same = { ...livingStates(), '2': { ...raw, other_metadata: 'poll-2' } }
    await rerender({ group: bedroom(same), snapshotStatus: 'recent-read', fixtureStates: same })
    await tick()
    expect(screen.getByText('Proposed adjustment · not sent')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dismiss review' })).toHaveFocus()
  })

  it('discards a draft after changed Hue brightness even within the same rounded percentage and restores focus', async () => {
    const initial = livingStates()
    const { rerender } = render(GroupSheet, {
      group: bedroom(initial), snapshotStatus: 'recent-read', fixtureStates: initial,
    })
    await openBedroomReview()
    // Both 178/254 and 179/254 round to the same displayed 70%.
    const changed = livingStates({ bri: 179 })
    await rerender({ group: bedroom(changed), snapshotStatus: 'recent-read', fixtureStates: changed })
    await tick()
    expect(screen.queryByText('Proposed adjustment · not sent')).not.toBeInTheDocument()
    const updatedSlider = screen.getByRole('slider', { name: /Draft Shaded desk lamp brightness percentage/ })
    expect(updatedSlider).toBeInstanceOf(HTMLInputElement)
    if (!(updatedSlider instanceof HTMLInputElement)) throw new Error('Brightness slider missing')
    expect(updatedSlider.value).toBe('70')
    expect(screen.getByRole('button', { name: 'Close lighting details' })).toHaveFocus()
  })

  it.each(['stale-read', 'disconnected', 'unverified'])('drops a focused review when status becomes %s', async (snapshotStatus) => {
    const initial = livingStates()
    const { rerender } = render(GroupSheet, {
      group: bedroom(initial), snapshotStatus: 'recent-read', fixtureStates: initial,
    })
    await openBedroomReview()
    await rerender({
      group: bedroom(initial),
      snapshotStatus: /** @type {'stale-read'|'disconnected'|'unverified'} */ (snapshotStatus),
      fixtureStates: initial,
    })
    await tick()
    expect(screen.queryByText('Proposed adjustment · not sent')).not.toBeInTheDocument()
    expect(screen.getByRole('slider', { name: /Draft Shaded desk lamp brightness percentage/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close lighting details' })).toHaveFocus()
  })
})
