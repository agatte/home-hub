import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import SceneTools from '../../src/lib/components/QuietAtlasSceneTools.svelte'
import { apiGet, apiPost } from '../../src/lib/api.js'
import { reviewSceneDraft } from '../../src/lib/quietAtlas/controlDraft.js'

vi.mock('../../src/lib/api.js', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

const rows = [{ id: 'golden_hour', display_name: 'Golden Hour', source: 'preset', lights: { '1': { on: true, bri: 150 } } }]
const reviewed = () => reviewSceneDraft('golden_hour', rows, { connected: true, loading: false, error: '' })
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.mocked(apiGet).mockImplementation(async path => path === '/api/scenes/effects'
    ? { available: true, effects: [{ name: 'candle', display_name: 'Candle' }] }
    : { scenes: rows })
})
afterEach(() => vi.restoreAllMocks())

describe('Functional scene tools', () => {
  it('only reads on mount and explicitly starts a guarded trial, then cancels it', async () => {
    vi.mocked(apiPost).mockImplementation(async path => path.endsWith('/cancel')
      ? { status: 'discarded' }
      : { status: 'ok', snapshot_id: 'test', revert_after: 30 })
    render(SceneTools, { scene: reviewed(), connected: true })
    await screen.findByRole('button', { name: 'Candle' })
    expect(apiPost).not.toHaveBeenCalled()
    await fireEvent.click(screen.getByRole('button', { name: 'Try for 30 seconds' }))
    await screen.findByText(/Preview acknowledged/)
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/scenes/golden_hour/try', {})
    expect(screen.getByRole('button', { name: 'Try for 30 seconds' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Candle' })).toBeDisabled()
    await fireEvent.click(screen.getByRole('button', { name: 'End active trial' }))
    await screen.findByText(/without restoring a superseded state/)
    expect(apiPost).toHaveBeenLastCalledWith('/api/scenes/try/cancel', {})
  })
  it('does not try a changed or missing scene', async () => {
    vi.mocked(apiGet).mockResolvedValue({ scenes: [] })
    render(SceneTools, { scene: reviewed(), connected: true })
    await fireEvent.click(screen.getByRole('button', { name: 'Try for 30 seconds' }))
    await screen.findByText(/Scene changed/)
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('reports partial effect results without marking an effect active', async () => {
    vi.mocked(apiPost).mockResolvedValue({ status: 'partial_failure', effect: 'candle' })
    render(SceneTools, { connected: true })
    await fireEvent.click(await screen.findByRole('button', { name: 'Candle' }))
    await screen.findByText(/Effect result incomplete/)
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/scenes/effects/candle', {})
    expect(screen.getByRole('button', { name: 'Candle' })).not.toHaveAttribute('aria-pressed', 'true')
  })
  it('disables trial and effect requests when disconnected', async () => {
    render(SceneTools, { scene: reviewed(), connected: false })
    expect(screen.getByRole('button', { name: 'Try for 30 seconds' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'End active trial' })).toBeDisabled()
    await waitFor(() => expect(apiPost).not.toHaveBeenCalled())
  })
})
