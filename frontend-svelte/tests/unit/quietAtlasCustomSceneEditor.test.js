import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import CustomSceneEditor from '../../src/lib/components/CustomSceneEditor.svelte'
import { lights } from '../../src/lib/stores/lights.js'
import { apiGet, apiPost, apiPut, apiDelete } from '../../src/lib/api.js'

vi.mock('../../src/lib/api.js', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  lights.set({
    '1': { light_id: '1', name: 'Living', on: true, bri: 100, hue: 8000, sat: 140, ct: 350, colormode: 'ct', reachable: true },
    '2': { light_id: '2', name: 'Desk', on: true, bri: 50, hue: 8000, sat: 140, reachable: false },
  })
  vi.mocked(apiGet).mockImplementation(async path => path.endsWith('/effects')
    ? { available: true, effects: [] }
    : { scenes: [{ id: 7, name: 'Saved scene', category: 'custom', light_states: { '1': { on: true, bri: 100, ct: 350 } } }] })
  vi.mocked(apiPost).mockResolvedValue({ status: 'ok', id: 8 })
  vi.mocked(apiPut).mockResolvedValue({ status: 'ok', id: 7 })
  vi.mocked(apiDelete).mockResolvedValue({ status: 'ok' })
})
afterEach(() => vi.restoreAllMocks())

it('captures reachable lights, edits a draft, and saves without any light writes', async () => {
  const onSave = vi.fn()
  render(CustomSceneEditor, { libraryOnly: true, onSave })
  const name = screen.getByRole('textbox', { name: 'Scene name' })
  await waitFor(() => expect(name).not.toBeDisabled())
  expect(screen.queryByRole('button', { name: 'Preview' })).not.toBeInTheDocument()
  expect(apiPost).not.toHaveBeenCalled()
  expect(apiPut).not.toHaveBeenCalled()
  await fireEvent.input(name, { target: { value: 'Reading' } })
  await fireEvent.input(screen.getByRole('slider', { name: 'Living brightness' }), { target: { value: '125' } })
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
  expect(apiPost).toHaveBeenCalledWith('/api/scenes/custom', { name: 'Reading', category: 'custom', effect: null, light_states: { '1': { on: true, bri: 125, ct: 350 } } })
  expect(apiPut).not.toHaveBeenCalled()
})

it('updates a loaded scene and does not send changes before Save', async () => {
  render(CustomSceneEditor, { libraryOnly: true, editingId: 7 })
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Scene name' })).toHaveValue('Saved scene'))
  await fireEvent.click(screen.getByRole('checkbox'))
  expect(apiPut).not.toHaveBeenCalled()
  await fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/api/scenes/custom/7', { name: 'Saved scene', category: 'custom', effect: null, light_states: { '1': { on: false, bri: 100, ct: 350 } } }))
})

it('blocks saving a scene that no longer exists', async () => {
  vi.mocked(apiGet).mockResolvedValue({ scenes: [], effects: [] })
  render(CustomSceneEditor, { libraryOnly: true, editingId: 999 })
  await screen.findByText('Scene no longer exists')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  expect(apiPut).not.toHaveBeenCalled()
})
