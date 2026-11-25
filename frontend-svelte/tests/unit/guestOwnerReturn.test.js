import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/svelte'
import GuestOwnerReturn from '../../src/lib/components/GuestOwnerReturn.svelte'
import layout from '../../src/routes/guest/+layout@.svelte?raw'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('only offers a fixed full-document return after an affirmative owner status', async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ authenticated: true }) })
  vi.stubGlobal('fetch', fetcher)
  render(GuestOwnerReturn)
  const link = await screen.findByRole('link', { name: 'Return to HomeHub' })
  expect(link).toHaveAttribute('href', '/')
  expect(link).toHaveAttribute('data-sveltekit-reload')
  expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/owner/session', expect.objectContaining({
    credentials: 'same-origin', cache: 'no-store', redirect: 'error'
  }))
  expect(layout).toContain('<GuestOwnerReturn />')
})

it.each([
  ['public gateway denial', { ok: false, json: async () => ({ authenticated: true }) }],
  ['locked device', { ok: true, json: async () => ({ authenticated: false }) }],
  ['malformed authority', { ok: true, json: async () => ({ authenticated: 'true' }) }],
  ['invalid body', { ok: true, json: async () => { throw new Error('invalid JSON') } }],
])('hides owner return for %s', async (_label, response) => {
  const fetcher = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetcher)
  render(GuestOwnerReturn)
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  await Promise.resolve()
  await Promise.resolve()
  expect(screen.queryByRole('link', { name: 'Return to HomeHub' })).not.toBeInTheDocument()
})

it('hides owner return when status is unavailable', async () => {
  const fetcher = vi.fn().mockRejectedValue(new Error('unavailable'))
  vi.stubGlobal('fetch', fetcher)
  render(GuestOwnerReturn)
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  expect(screen.queryByRole('link', { name: 'Return to HomeHub' })).not.toBeInTheDocument()
})
