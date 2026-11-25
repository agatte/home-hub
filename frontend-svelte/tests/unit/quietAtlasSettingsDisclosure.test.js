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

it('discloses the grouped section list, navigates once, and reflects the URL-selected section', async () => {
  const onSelect = vi.fn()
  const { container, rerender } = render(SettingsRail, { sections, activeId: 'overview', onSelect })
  const trigger = container.querySelector('button.phone-section-trigger')
  if (!trigger) throw new Error('Missing compact section trigger')
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  expect(trigger).toHaveTextContent('Overview')
  expect(onSelect).not.toHaveBeenCalled()
  await fireEvent.click(trigger)
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  const nav = screen.getByRole('navigation', { name: 'Settings sections' })
  expect(within(nav).getByText('How HomeHub behaves')).toBeInTheDocument()
  expect(within(nav).getByRole('button', { name: /Overview/ })).toHaveAttribute('aria-current', 'page')
  await fireEvent.click(within(nav).getByRole('button', { name: /Automation/ }))
  expect(onSelect).toHaveBeenCalledExactlyOnceWith('automation')
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await rerender({ activeId: 'automation' })
  expect(trigger).toHaveTextContent('Automation')
  await fireEvent.click(trigger)
  await fireEvent.click(within(nav).getByRole('button', { name: /Automation/ }))
  expect(onSelect).toHaveBeenCalledTimes(1)
  await rerender({ activeId: 'overview' })
  expect(trigger).toHaveTextContent('Overview')
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
