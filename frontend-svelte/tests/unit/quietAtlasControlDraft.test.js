import { describe, expect, it } from 'vitest'
import { describeFixture, buildLightingOverview } from '../../src/lib/quietAtlas/lightingModel.js'
import { canDraftBrightness, reviewBrightnessDraft, reviewSceneDraft } from '../../src/lib/quietAtlas/controlDraft.js'
import groupSheet from '../../src/lib/components/QuietAtlasGroupSheet.svelte?raw'
import sceneBrowser from '../../src/lib/components/QuietAtlasSceneBrowser.svelte?raw'
import experience from '../../src/lib/components/QuietAtlasLightingExperience.svelte?raw'

const fixture = describeFixture({
  light_id: '2', name: 'Desk left', on: true, reachable: true, bri: 178,
}, '2')
const scenes = [
  { id: 'golden_hour', display_name: 'Golden Hour', source: 'preset', category: 'cozy' },
  { id: 'custom_17', display_name: 'Reading', source: 'custom' },
  { id: 'scene-uuid', display_name: 'Hue Afternoon', source: 'bridge' },
]
const sceneStatus = { connected: true, loading: false, error: '' }

describe('Quiet Atlas reviewed, strictly local future control intents', () => {
  it('converts explicit percentage drafts into single-light Hue units, never grouping them', () => {
    expect(canDraftBrightness(fixture, 'recent-read')).toBe(true)
    expect(reviewBrightnessDraft(fixture, 'recent-read', 75)).toEqual({
      fixtureId: '2', name: 'Desk left', fromPercent: 70, toPercent: 75,
      proposedBri: 191, scope: 'single-fixture',
    })
  })

  it('refuses off, unreachable, unknown, stale, unexpected fixture or invalid adjustments', () => {
    const valid = reviewBrightnessDraft(fixture, 'recent-read', 75)
    expect(valid).toMatchObject({ toPercent: 75, proposedBri: 191, scope: 'single-fixture' })
    for (const source of [
      describeFixture(undefined, '2'),
      describeFixture({ light_id: '2', reachable: true, on: false, bri: 178 }, '2'),
      describeFixture({ light_id: '2', reachable: false, on: true, bri: 100 }, '2'),
      describeFixture({ light_id: '2', reachable: true, bri: 100 }, '2'),
      describeFixture({ light_id: 'unexpected', reachable: true, on: true, bri: 100 }, 'unexpected'),
    ]) {
      expect(canDraftBrightness(source, 'recent-read')).toBe(false)
      expect(reviewBrightnessDraft(source, 'recent-read', 55)).toBeNull()
    }
    for (const status of ['unverified', 'disconnected', 'stale-read', 'made-up']) {
      expect(reviewBrightnessDraft(fixture, status, 75)).toBeNull()
    }
    for (const pct of [-1, 0, 101, 5.5, Infinity, NaN, '20', null, undefined, 70]) {
      expect(reviewBrightnessDraft(fixture, 'recent-read', pct)).toBeNull()
    }
    expect(buildLightingOverview({ '2': { light_id: '2', reachable: true, on: true, bri: 178 } })
      .find((group) => group.id === 'bedroom')?.supportsGroupWrite).toBe(false)
  })

  it('plans only scenes sourced from the actual list with connection and no active error', () => {
    expect(reviewSceneDraft('golden_hour', scenes, sceneStatus)).toMatchObject({
      id: 'golden_hour', name: 'Golden Hour', source: 'preset',
    })
    expect(reviewSceneDraft('custom_17', scenes, sceneStatus)?.description).toContain('custom')
    expect(reviewSceneDraft('scene-uuid', scenes, sceneStatus)?.description).toContain('manifest')
    for (const id of ['unknown', '', '../activate', '__proto__', null]) {
      expect(reviewSceneDraft(id, scenes, sceneStatus)).toBeNull()
    }
    expect(reviewSceneDraft('golden_hour', scenes, { ...sceneStatus, connected: false })).toBeNull()
    expect(reviewSceneDraft('golden_hour', scenes, { ...sceneStatus, loading: true })).toBeNull()
    expect(reviewSceneDraft('golden_hour', scenes, { ...sceneStatus, error: 'read failed' })).toBeNull()
    expect(reviewSceneDraft('golden_hour', [], sceneStatus)).toBeNull()
  })

  it('keeps actuation disabled while making drafts reviewable and clearly non-sending', () => {
    expect(groupSheet).toContain('reviewBrightnessDraft(fixture, snapshotStatus')
    expect(groupSheet).toContain('Review adjustment')
    expect(groupSheet).toContain('Nothing is sent to HomeHub')
    expect(groupSheet).toContain('Proposed adjustment · not sent')
    expect(groupSheet).toContain("snapshotStatus !== 'recent-read'")
    expect(groupSheet).toContain('on:click={dismissBrightnessReview}')
    expect(groupSheet).toContain('await tick()')
    expect(sceneBrowser).toContain('Review preset impact')
    expect(sceneBrowser).toContain('on:click={dismissSceneReview}')
    expect(sceneBrowser).toContain('if (!connected || loading || error) requestedReviewId = null')
    expect(sceneBrowser).toContain('No scene command has been sent.')
    expect(sceneBrowser).toContain('reviewSceneDraft(')
    expect(experience).toContain('cannot turn on lights, change brightness, apply scenes')
    for (const source of [groupSheet, sceneBrowser, experience]) {
      expect(source).not.toMatch(/\b(apiPut|apiPost|optimisticLightPatch|setLight|activateScene)\s*\(/)
      expect(source).not.toMatch(/fetch\s*\([^\n]*(?:method:\s*['"](?:POST|PUT|PATCH|DELETE))/)
    }
  })
})
