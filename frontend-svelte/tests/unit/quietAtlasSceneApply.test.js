import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import { tick } from 'svelte'
import SceneApply from '../../src/lib/components/QuietAtlasSceneApply.svelte'
import { apiGet, apiPost } from '../../src/lib/api.js'
import { reviewSceneDraft } from '../../src/lib/quietAtlas/controlDraft.js'

vi.mock('../../src/lib/api.js', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

const rows = [{ id: 'golden_hour', display_name: 'Golden Hour', source: 'preset', lights: { '1': { on: true, bri: 150 } } }]
const reviewed = () => reviewSceneDraft('golden_hour', rows, { connected: true, loading: false, error: '' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  vi.mocked(apiGet).mockResolvedValue({ scenes: rows })
  vi.mocked(apiPost).mockResolvedValue({ status: 'ok' })
})
afterEach(() => vi.restoreAllMocks())

describe('Functional scene application in Control', () => {
  it('does not send commands on mount or when disconnected', async () => {
    render(SceneApply, { scene: reviewed(), connected: false })
    expect(screen.getByRole('button', { name: 'Apply scene' })).toBeDisabled()
    await tick()
    expect(apiGet).not.toHaveBeenCalled()
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('explicitly applies a revalidated scene exactly once and reports acknowledgement', async () => {
    const onApplied = vi.fn()
    render(SceneApply, { scene: reviewed(), connected: true, onApplied })
    expect(apiPost).not.toHaveBeenCalled()
    await fireEvent.click(screen.getByRole('button', { name: 'Apply scene' }))
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1))
    expect(apiPost).toHaveBeenCalledWith('/api/scenes/golden_hour/activate', {})
    expect(apiGet).toHaveBeenCalledWith('/api/scenes')
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
    expect(screen.getByText(/Scene acknowledged/)).toBeInTheDocument()
  })
  it('does not activate a changed or missing scene', async () => {
    vi.mocked(apiGet).mockResolvedValue({ scenes: [] })
    render(SceneApply, { scene: reviewed(), connected: true })
    await fireEvent.click(screen.getByRole('button', { name: 'Apply scene' }))
    await waitFor(() => expect(screen.getByText(/Scene changed or is unavailable/)).toBeInTheDocument())
    expect(apiPost).not.toHaveBeenCalled()
  })
  it('reports a denied or failed command without a success claim', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('POST failed: 403'))
    const onApplied = vi.fn()
    render(SceneApply, { scene: reviewed(), connected: true, onApplied })
    await fireEvent.click(screen.getByRole('button', { name: 'Apply scene' }))
    await waitFor(() => expect(screen.getByText(/Scene could not be confirmed/)).toBeInTheDocument())
    expect(onApplied).not.toHaveBeenCalled()
  })
})
