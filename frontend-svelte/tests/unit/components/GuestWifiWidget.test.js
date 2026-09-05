import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/svelte'
import QRCode from 'qrcode'
import { apiGet } from '$lib/api.js'

import GuestWifiWidget from '$lib/components/GuestWifiWidget.svelte'

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn() },
}))

vi.mock('$lib/api.js', () => ({
  apiGet: vi.fn(),
}))

const freshInfo = {
  configured: true,
  ssid: 'Mercury_Guest',
  qr_payload: 'WIFI:T:WPA;S:Mercury_Guest;P:new;H:false;;',
  guest_app_configured: false,
}

async function settleMount() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}
beforeEach(() => {
  vi.mocked(apiGet).mockResolvedValue(freshInfo)
  vi.mocked(QRCode.toDataURL).mockResolvedValue('data:image/png;base64,qr')
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('GuestWifiWidget open action', () => {
  it('fetches current Wi-Fi data before generating the QR', async () => {
    const { component } = render(GuestWifiWidget)
    await settleMount()
    vi.mocked(apiGet).mockClear()
    vi.mocked(QRCode.toDataURL).mockClear()
    vi.mocked(apiGet).mockResolvedValueOnce(freshInfo)

    await component.openModal()

    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(apiGet).toHaveBeenCalledWith('/api/guest/wifi')
    expect(QRCode.toDataURL).toHaveBeenCalledWith(freshInfo.qr_payload, expect.any(Object))
  })

  it('fails closed instead of generating a stale QR when refresh fails', async () => {
    const { component } = render(GuestWifiWidget)
    await settleMount()
    vi.mocked(apiGet).mockClear()
    vi.mocked(QRCode.toDataURL).mockClear()
    vi.mocked(apiGet).mockRejectedValueOnce(new TypeError('offline'))

    await component.openModal()

    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(QRCode.toDataURL).not.toHaveBeenCalled()
  })
})
