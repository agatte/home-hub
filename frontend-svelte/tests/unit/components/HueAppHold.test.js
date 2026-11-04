import { render, fireEvent, screen, waitFor, cleanup } from '@testing-library/svelte'
import { afterEach, it, expect, vi } from 'vitest'
import HueAppHold from '../../../src/lib/components/HueAppHold.svelte'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

it('requires confirmation, performs no mount/destroy request, and releases the exact token', async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce({ status: 200, json: async () => ({ status: 'held', stamp: 'same-version' }) })
    .mockResolvedValueOnce({ status: 200, json: async () => ({ status: 'released' }) })
  vi.stubGlobal('fetch', fetcher)
  const view = render(HueAppHold)
  expect(fetcher).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Hold L6', hidden: true }).disabled).toBe(true)
  await fireEvent.click(view.container.querySelector('summary'))
  await fireEvent.click(screen.getByRole('checkbox'))
  await fireEvent.click(screen.getByRole('button', { name: 'Hold L6' }))
  await waitFor(() => expect(screen.getByText(/Hold acknowledged/)).toBeTruthy())
  await fireEvent.click(screen.getByRole('button', { name: 'Release saved L6 ownership' }))
  await waitFor(() => expect(screen.getByText(/Release acknowledged/)).toBeTruthy())
  expect(fetcher.mock.calls[1][1].body).toBe('{"stamp":"same-version"}')
  view.unmount()
  expect(fetcher).toHaveBeenCalledTimes(2)
})

it('labels a recovered token unverified without contacting the server', async () => {
  sessionStorage.setItem('homehub:hue-app-hold:6', '{"stamp":"cached"}')
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  render(HueAppHold)
  await waitFor(() => expect(screen.getByText(/Saved release token recovered/)).toBeTruthy())
  expect(fetcher).not.toHaveBeenCalled()
})

it('can discard a stale 409 token locally without issuing another ownership write', async () => {
  sessionStorage.setItem('homehub:hue-app-hold:6', '{"stamp":"old"}')
  const fetcher = vi.fn().mockResolvedValue({
    status: 409, json: async () => ({ detail: 'Hold stamp changed or expired' }),
  })
  vi.stubGlobal('fetch', fetcher)
  const view = render(HueAppHold)
  await waitFor(() => expect(screen.getByText(/Saved release token recovered/)).toBeTruthy())
  await fireEvent.click(view.container.querySelector('summary'))
  await fireEvent.click(screen.getByRole('button', { name: 'Release saved L6 ownership' }))
  await waitFor(() => expect(screen.getByText(/Ownership changed \(409\)/)).toBeTruthy())
  await fireEvent.click(screen.getByRole('button', { name: /Forget stale local token/ }))
  expect(sessionStorage.getItem('homehub:hue-app-hold:6')).toBeNull()
  expect(fetcher).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Hold L6' }).disabled).toBe(true)
})
