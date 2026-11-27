import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/svelte'
import { goto } from '$app/navigation'
import ClassicBookmark from '../../src/routes/classic/+page.svelte'
import { classicBookmarkHref, activeQuietAtlasSection } from '../../src/lib/quietAtlas/navigation.js'

vi.mock('$app/navigation', () => ({ goto: vi.fn() }))

let originalUrl = ''
beforeEach(() => {
  originalUrl = window.location.pathname + window.location.search + window.location.hash
  vi.mocked(goto).mockReset()
  vi.mocked(goto).mockResolvedValue(undefined)
})
afterEach(() => {
  cleanup()
  window.history.replaceState(null, '', originalUrl)
})

it.each([
  ['/classic', '/'],
  ['/classic#apartment-controls', '/quiet-atlas/control'],
  ['/classic?next=https://example.com#other', '/'],
  ['/classic#//example.com', '/'],
])('replaces %s with its fixed HomeHub destination %s', async (url, destination) => {
  window.history.replaceState(null, '', url)
  render(ClassicBookmark)
  await waitFor(() => expect(goto).toHaveBeenCalledExactlyOnceWith(destination, { replaceState: true }))
  expect(screen.getByRole('link', { name: 'Continue to HomeHub' })).toHaveAttribute('href', destination)
  expect(screen.queryByRole('button')).toBeNull()
})

it('leaves an ordinary safe link when client navigation fails', async () => {
  window.history.replaceState(null, '', '/classic#apartment-controls')
  vi.mocked(goto).mockRejectedValueOnce(new Error('navigation failed'))
  render(ClassicBookmark)
  await waitFor(() => expect(goto).toHaveBeenCalledExactlyOnceWith('/quiet-atlas/control', { replaceState: true }))
  expect(screen.getByRole('link', { name: 'Continue to HomeHub' })).toHaveAttribute('href', '/quiet-atlas/control')
})

it('maps only the known legacy fragment and never arbitrary redirect targets', () => {
  expect(classicBookmarkHref('#apartment-controls')).toBe('/quiet-atlas/control')
  for (const hash of ['', '#//other.example', '#https://other.example', '#%61partment-controls']) expect(classicBookmarkHref(hash)).toBe('/')
  expect(activeQuietAtlasSection('/classic')).toBe('home')
  expect(activeQuietAtlasSection('/classic', '#apartment-controls')).toBe('control')
})
