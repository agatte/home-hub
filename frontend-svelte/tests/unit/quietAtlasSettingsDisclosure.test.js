import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/svelte'
import SettingsRail from '../../src/lib/components/settings/SettingsRail.svelte'
import OverviewSection from '../../src/routes/settings/sections/OverviewSection.svelte'
import { apiGet, apiPost } from '../../src/lib/api.js'

vi.mock('../../src/lib/api.js', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
const sections = [
  { id: 'overview', label: 'Overview', group: 'Systems & access', hint: 'Connections' },
  { id: 'automation', label: 'Automation', group: 'How HomeHub behaves', hint: 'Detection' },
  { id: 'audio', label: 'Audio', group: 'Listening & experiences', hint: 'Speaker preferences' },
]
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiGet).mockResolvedValue({ build_id: 'test' })
  vi.mocked(apiPost).mockResolvedValue({ status: 'ok' })
})
afterEach(() => vi.restoreAllMocks())

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
