import { beforeEach, describe, expect, it, vi } from 'vitest'
import { get } from 'svelte/store'

vi.mock('$lib/api.js', () => ({ apiGet: vi.fn() }))

import { apiGet } from '$lib/api.js'
import { dispatchGamedayMessage, fetchGamedayInitial, gameday } from '$lib/stores/gameday.js'

beforeEach(() => {
  vi.mocked(apiGet).mockReset()
  gameday.set({
    state: null,
    lastPlay: null,
    viewerState: null,
    viewerSync: null,
    viewerSyncLoaded: false,
    lastCelebration: null,
    schedule: [],
    scheduleLoaded: false,
  })
})

describe('Game Day viewer sync store', () => {
  it('keeps canonical and viewer-aligned state separate', () => {
    dispatchGamedayMessage('gameday_state', { status: 'in-progress', clock: '8:00' })
    dispatchGamedayMessage('gameday_viewer_state', { status: 'in-progress', clock: '8:30' })

    const current = get(gameday)
    expect(current.state.clock).toBe('8:00')
    expect(current.viewerState.clock).toBe('8:30')
  })

  it('tracks viewer-clock authority independently of canonical state', () => {
    dispatchGamedayMessage('gameday_state', { status: 'in-progress', clock: '7:12' })
    dispatchGamedayMessage('gameday_viewer_sync', {
      enabled: true,
      active: true,
      authoritative: false,
      reason: 'forward_seek',
    })

    const current = get(gameday)
    expect(current.state.clock).toBe('7:12')
    expect(current.viewerSync.active).toBe(true)
    expect(current.viewerSync.authoritative).toBe(false)
    expect(current.viewerSync.reason).toBe('forward_seek')
  })

  it('collapses viewer no-game sentinel to null without changing canonical state', () => {
    dispatchGamedayMessage('gameday_state', { status: 'in-progress', clock: '2:00' })
    dispatchGamedayMessage('gameday_viewer_state', { status: 'no-game' })

    const current = get(gameday)
    expect(current.state.clock).toBe('2:00')
    expect(current.viewerState).toBeNull()
  })

  it('marks viewer-sync knowledge resolved without exposing retained viewer state', () => {
    dispatchGamedayMessage('gameday_state', { status: 'in-progress', clock: '6:10' })
    dispatchGamedayMessage('gameday_viewer_state', { status: 'in-progress', clock: '7:02' })
    dispatchGamedayMessage('gameday_viewer_sync', {
      enabled: true,
      presentation_active: true,
      reason: 'backward_seek',
    })

    // The sync status arrives before the backend's explicit null frame. Clear
    // locally in the same dispatch so Svelte cannot paint the stale future frame.
    const afterStatus = get(gameday)
    expect(afterStatus.viewerState).toBeNull()

    dispatchGamedayMessage('gameday_viewer_state', null)
    const current = get(gameday)
    expect(current.viewerSyncLoaded).toBe(true)
    expect(current.state.clock).toBe('6:10')
    expect(current.viewerState).toBeNull()
  })

  it('does not restore a stale REST viewer frame after newer WS invalidation', async () => {
    dispatchGamedayMessage('gameday_viewer_state', { status: 'in-progress', clock: '7:02' })
    dispatchGamedayMessage('gameday_viewer_sync', {
      enabled: true,
      presentation_active: true,
      reason: 'normal',
    })

    /** @type {(value: any) => void} */
    let resolveViewerSync = () => {}
    const viewerSyncResponse = new Promise((resolve) => { resolveViewerSync = resolve })
    vi.mocked(apiGet)
      .mockReturnValueOnce(viewerSyncResponse)
      .mockResolvedValueOnce({ status: 'in-progress', clock: '6:10' })
      .mockResolvedValueOnce([])

    const prime = fetchGamedayInitial()
    dispatchGamedayMessage('gameday_viewer_sync', {
      enabled: true,
      presentation_active: true,
      reason: 'backward_seek',
    })
    expect(get(gameday).viewerState).toBeNull()

    resolveViewerSync({
      enabled: true,
      presentation_active: true,
      reason: 'normal',
      viewer_state: { status: 'in-progress', clock: '7:02' },
    })
    await prime

    const current = get(gameday)
    expect(current.viewerSync.reason).toBe('backward_seek')
    expect(current.viewerState).toBeNull()
  })

})
