import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/svelte'
import { guestState, initGuestState } from '$lib/stores/guest.js'
import GuestWelcome from '../../src/routes/guest/+page.svelte'
import layout from '../../src/routes/guest/+layout@.svelte?raw'
import navigation from '../../src/lib/components/GuestBottomNav.svelte?raw'
import wifi from '../../src/routes/guest/wifi/+page.svelte?raw'
import vibe from '../../src/routes/guest/vibe/+page.svelte?raw'

vi.mock('$lib/stores/guest.js', async () => {
  const { writable } = await import('svelte/store')
  return { guestState: writable({}), initGuestState: vi.fn(() => () => {}) }
})

const base = { mode: 'idle', source: null, manual_override: false, lights: [] }

beforeEach(() => {
  guestState.set({ ...base, sonos: { state: 'disconnected', has_art: false } })
  vi.mocked(initGuestState).mockClear()
})
afterEach(cleanup)

it('provides explicit guest-only entry points without requiring a live speaker report', () => {
  render(GuestWelcome)
  expect(screen.getByRole('heading', { name: 'Welcome in.' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Connect to Wi-Fi' })).toHaveAttribute('href', '/guest/wifi')
  expect(screen.getByRole('link', { name: /The bar/ })).toHaveAttribute('href', '/guest/bar')
  expect(screen.getByRole('link', { name: /The plants/ })).toHaveAttribute('href', '/guest/plants')
  expect(screen.getByRole('link', { name: /Set the vibe/ })).toHaveAttribute('href', '/guest/vibe')
  expect(screen.getByRole('link', { name: /Music & atmosphere/ })).toHaveAttribute('href', '/guest/vibe')
  expect(screen.getByText('Music status unavailable')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'House notes' })).toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(4)
  expect(initGuestState).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button')).toBeNull()
})

it('displays reported music and same-origin artwork, not a guessed track', () => {
  guestState.set({ ...base, sonos: { state: 'PLAYING', track: 'A & B', artist: 'Artist', has_art: true } })
  render(GuestWelcome)
  expect(screen.getByText('A & B')).toBeInTheDocument()
  expect(screen.getByText('Artist')).toBeInTheDocument()
  expect(screen.getByAltText('Album artwork')).toHaveAttribute('src', '/api/guest/art?track=A%20%26%20B')
  expect(screen.queryByText('Music status unavailable')).toBeNull()
})

it('distinguishes stopped playback from unavailable metadata', () => {
  guestState.set({ ...base, sonos: { state: 'STOPPED', has_art: false } })
  const view = render(GuestWelcome)
  expect(screen.getByText('Nothing playing right now')).toBeInTheDocument()
  view.unmount()
  guestState.set({ ...base, sonos: { state: 'PLAYING', has_art: false } })
  render(GuestWelcome)
  expect(screen.getByText('Music is playing')).toBeInTheDocument()
  expect(screen.getByText('Track information unavailable.')).toBeInTheDocument()
})

it('keeps the established guest routes, owner return and guarded controls', () => {
  expect(layout).toContain('<GuestOwnerReturn />')
  expect(layout).toContain('<GuestBottomNav />')
  for (const href of ['/guest', '/guest/wifi', '/guest/bar', '/guest/plants', '/guest/vibe']) expect(navigation).toContain("href: '" + href + "'")
  expect(navigation).toContain('aria-current=')
  expect(wifi).toContain('<GuestWifiWidget quietAtlas />')
  for (const handler of ['activateScene(scene.name)', 'activateVibe(vibe.name)', 'togglePlayPause', 'skipNext', 'handBack', 'sendToast']) expect(vibe).toContain(handler)
})
