import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte'
import { apiGet } from '$lib/api.js'
import QRCode from 'qrcode'
import PlantWidget from '../../src/lib/components/PlantWidget.svelte'
import BarWidget from '../../src/lib/components/BarWidget.svelte'
import GuestWifiWidget from '../../src/lib/components/GuestWifiWidget.svelte'

vi.mock('$lib/api.js', () => ({ apiGet: vi.fn() }))
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn() } }))

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(apiGet).mockRejectedValue(new Error('unavailable'))
  vi.mocked(QRCode.toDataURL).mockResolvedValue('data:image/png;base64,fixture')
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('opens Plants despite unavailable summary and offers external recovery', async () => {
  render(PlantWidget)
  await screen.findByText('Plant app unavailable')
  await fireEvent.click(screen.getByRole('button', { name: /Open Plants/ }))
  expect(await screen.findByTitle('Plant Care App')).toBeInTheDocument()
  const link = screen.getByRole('link', { name: /Open in browser/ })
  expect(link).toHaveAttribute('href', 'https://plant-care-app-gamma.vercel.app')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  await fireEvent.click(screen.getByRole('button', { name: 'Close plant app' }))
  expect(screen.queryByTitle('Plant Care App')).toBeNull()
})

it('opens configured Home Bar without summary and offers external recovery', async () => {
  vi.mocked(apiGet).mockResolvedValue({ bar_summary: null, bar_app_url: 'https://bar.example.test/' })
  render(BarWidget)
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/bar/status'))
  await fireEvent.click(screen.getByRole('button', { name: /Open Home Bar/ }))
  expect(await screen.findByTitle('Home Bar')).toHaveAttribute('src', 'https://bar.example.test/')
  expect(screen.getByRole('link', { name: /Open in browser/ })).toHaveAttribute('href', 'https://bar.example.test/')
  await fireEvent.click(screen.getByRole('button', { name: 'Close bar app' }))
  expect(screen.queryByTitle('Home Bar')).toBeNull()
})

it.each([null, 'javascript:alert(1)'])('reports unavailable Home Bar address and permits retry (%s)', async (url) => {
  vi.mocked(apiGet).mockResolvedValue({ bar_summary: null, bar_app_url: url })
  render(BarWidget)
  await fireEvent.click(screen.getByRole('button', { name: /Open Home Bar/ }))
  expect(await screen.findByRole('status')).toHaveTextContent('Home Bar address unavailable')
  expect(screen.queryByTitle('Home Bar')).toBeNull()
  vi.mocked(apiGet).mockResolvedValue({ bar_summary: null, bar_app_url: 'https://bar.example.test/' })
  await fireEvent.click(screen.getByRole('button', { name: /Open Home Bar/ }))
  expect(await screen.findByTitle('Home Bar')).toBeInTheDocument()
})

it.each([true, false])('preserves QR generation and selects owner portal theme only when requested (%s)', async (quietAtlas) => {
  vi.mocked(apiGet).mockResolvedValue({ configured: true, ssid: 'Fixture', qr_payload: 'WIFI:fixture', guest_app_configured: false })
  const fetcher = vi.fn()
  vi.stubGlobal('fetch', fetcher)
  render(GuestWifiWidget, { quietAtlas })
  await fireEvent.click(await screen.findByRole('button', { name: /Show QR/ }))
  const dialog = await screen.findByRole('dialog', { name: 'Guest WiFi' })
  const portal = dialog.parentElement
  expect(portal.parentElement).toBe(document.body)
  expect(portal.classList.contains('hh-portal-surface')).toBe(quietAtlas)
  expect(QRCode.toDataURL).toHaveBeenCalledWith('WIFI:fixture', expect.objectContaining({ color: { dark: '#000000', light: '#ffffff' } }))
  expect(fetcher).not.toHaveBeenCalled()
  await fireEvent.click(screen.getByRole('button', { name: 'Close guest WiFi' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})
