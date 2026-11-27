import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import SettingsRail from '../../src/lib/components/settings/SettingsRail.svelte'
import OverviewSection from '../../src/routes/settings/sections/OverviewSection.svelte'
import { connected, deviceStatus } from '../../src/lib/stores/connection.js'
import { apiPost } from '../../src/lib/api.js'

vi.mock('../../src/lib/api.js', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
const sections = [
  { id: 'overview', label: 'Overview', group: 'Systems & access', hint: 'Connections' },
  { id: 'automation', label: 'Automation', group: 'How HomeHub behaves', hint: 'Detection' },
  { id: 'audio', label: 'Audio', group: 'Listening & experiences', hint: 'Speaker preferences' },
]
beforeEach(() => {
  vi.clearAllMocks()
  connected.set(false)
  deviceStatus.set({ hue: false, sonos: false })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, json: async () => ({ status: 'healthy', build_id: 'test', devices: { hue_bridge: true, sonos: true, pihole: true } }),
  }))
  vi.mocked(apiPost).mockResolvedValue({ status: 'ok' })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('opens sections from the index, exposes the direct parent and follows restored URL state', async () => {
  const onSelect = vi.fn()
  const { rerender } = render(SettingsRail, { sections, activeId: 'overview', indexView: true, indexHref: '/settings?source=kiosk', onSelect })
  const nav = screen.getByRole('navigation', { name: 'Settings sections' })
  expect(screen.queryByRole('link', { name: 'Back to Settings sections' })).not.toBeInTheDocument()
  expect(within(nav).getByText('How HomeHub behaves')).toBeInTheDocument()
  expect(within(nav).getByRole('button', { name: /Overview/ })).not.toHaveAttribute('aria-current')
  expect(onSelect).not.toHaveBeenCalled()
  await fireEvent.click(within(nav).getByRole('button', { name: /Overview/ }))
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('overview')
  await rerender({ activeId: 'overview', indexView: false })
  expect(screen.getByRole('link', { name: 'Back to Settings sections' })).toHaveAttribute('href', '/settings?source=kiosk')
  expect(within(nav).getByRole('button', { name: /Overview/ })).toHaveAttribute('aria-current', 'page')
  await fireEvent.click(within(nav).getByRole('button', { name: /Overview/ }))
  expect(onSelect).toHaveBeenCalledTimes(1)
  await rerender({ activeId: 'automation', indexView: false })
  expect(screen.getByRole('link', { name: 'Back to Settings sections' })).toHaveTextContent('Automation')
  await rerender({ activeId: 'overview', indexView: true })
  expect(screen.queryByRole('link', { name: 'Back to Settings sections' })).not.toBeInTheDocument()
  expect(within(nav).getByRole('button', { name: /Overview/ })).not.toHaveAttribute('aria-current')
})

it('keeps diagnostic actions behind a disclosure and never sends merely by opening it', async () => {
  const { container } = render(OverviewSection)
  const details = container.querySelector('details.diagnostics')
  if (!details) throw new Error('Missing diagnostics')
  expect(details).not.toHaveAttribute('open')
  expect(apiPost).not.toHaveBeenCalled()
  const summary = details.querySelector('summary')
  if (!summary) throw new Error('Missing diagnostic summary')
  await fireEvent.click(summary)
  expect(details).toHaveAttribute('open')
  expect(apiPost).not.toHaveBeenCalled()
  await fireEvent.click(screen.getByRole('button', { name: 'Test TTS' }))
  expect(apiPost).toHaveBeenCalledExactlyOnceWith('/api/sonos/tts', { text: 'Home Hub is connected and working.', volume: 10 })
})

function connectionRow(label) {
  const row = screen.getByText(label, { exact: true }).closest('.settings-row')
  if (!(row instanceof HTMLElement)) throw new Error(`Missing connection row: ${label}`)
  return within(row)
}

it('separates reachable backend and healthy devices from a disconnected browser socket', async () => {
  render(OverviewSection)
  await waitFor(() => expect(connectionRow('Server').getByText('Reachable')).toBeInTheDocument())
  expect(connectionRow('Live updates').getByText('Disconnected')).toBeInTheDocument()
  expect(connectionRow('Hue Bridge').getByText('Connected')).toBeInTheDocument()
  expect(connectionRow('Sonos Era 100').getByText('Connected')).toBeInTheDocument()
  expect(connectionRow('Pi-hole').getByText('Connected')).toBeInTheDocument()
  expect(apiPost).not.toHaveBeenCalled()
})

it('uses explicit negative health evidence and never stale positive socket flags', async () => {
  connected.set(true)
  deviceStatus.set({ hue: true, sonos: true })
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
    status: 'degraded', devices: { hue_bridge: false },
  })))
  render(OverviewSection)
  await waitFor(() => expect(connectionRow('Server').getByText('Degraded')).toBeInTheDocument())
  expect(connectionRow('Live updates').getByText('Connected')).toBeInTheDocument()
  expect(connectionRow('Hue Bridge').getByText('Offline')).toHaveClass('offline')
  expect(connectionRow('Sonos Era 100').getByText('Unknown')).not.toHaveClass('offline')
  expect(connectionRow('Pi-hole').getByText('Unknown')).not.toHaveClass('offline')
})

it('invalidates a previous health snapshot on resume and recovers with fresh evidence', async () => {
  render(OverviewSection)
  await waitFor(() => expect(connectionRow('Hue Bridge').getByText('Connected')).toBeInTheDocument())
  vi.mocked(fetch).mockRejectedValueOnce(new Error('network'))
  await fireEvent(document, new Event('visibilitychange'))
  await waitFor(() => expect(connectionRow('Server').getByText('Unverified')).toBeInTheDocument())
  expect(connectionRow('Hue Bridge').getByText('Unknown')).toBeInTheDocument()
  expect(connectionRow('Sonos Era 100').getByText('Unknown')).toBeInTheDocument()
  await fireEvent(document, new Event('visibilitychange'))
  await waitFor(() => expect(connectionRow('Server').getByText('Reachable')).toBeInTheDocument())
  expect(connectionRow('Hue Bridge').getByText('Connected')).toBeInTheDocument()
})

it('aborts a pending health read when the section is unmounted', async () => {
  vi.mocked(fetch).mockImplementation(() => new Promise(() => {}))
  const { unmount } = render(OverviewSection)
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  const signal = vi.mocked(fetch).mock.calls[0]?.[1]?.signal
  if (!signal) throw new Error('Missing health request abort signal')
  expect(signal.aborted).toBe(false)
  unmount()
  expect(signal.aborted).toBe(true)
})
