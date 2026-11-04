// L6 pilot only. Same-origin fetch follows api.js; keep non-OK JSON here
// because a 503 can carry the only recovery token. Never log response bodies.
export const HOLD_KEY = 'homehub:hue-app-hold:6'
const validStamp = value => typeof value === 'string' && value.length > 0 && value.length <= 64

export function recoverHold(storage) {
  try {
    const value = JSON.parse(storage.getItem(HOLD_KEY))
    return validStamp(value?.stamp) ? { stamp: value.stamp, kind: 'unverified' } : null
  } catch { return null }
}

export function saveHold(storage, state) {
  try {
    if (state?.stamp) storage.setItem(HOLD_KEY, JSON.stringify({ stamp: state.stamp }))
    else storage.removeItem(HOLD_KEY)
    return true
  } catch { return false }
}

export function interpretHold(status, body, releasing, previous = null) {
  const detail = body?.detail && typeof body.detail === 'object' ? body.detail : body
  if (status >= 200 && status < 300) {
    if (releasing && body?.status === 'released') return { kind: 'released', stamp: null }
    if (!releasing && body?.status === 'held' && validStamp(body.stamp)) {
      return { kind: 'acknowledged', stamp: body.stamp }
    }
  }
  if (status === 409) return { kind: 'conflict', stamp: previous?.stamp ?? null }
  return {
    kind: 'uncertain',
    stamp: (status === 503 && validStamp(detail?.stamp) ? detail.stamp : previous?.stamp) ?? null,
    activeInMemory: status === 503 && typeof detail?.active_in_memory === 'boolean'
      ? detail.active_in_memory : null,
  }
}

export async function requestHold(releasing, previous, fetcher = fetch) {
  if (releasing && !validStamp(previous?.stamp)) throw new Error('Missing matching stamp')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8000)
  try {
    const response = await fetcher('/api/lights/6/hue-app-hold', {
      method: releasing ? 'DELETE' : 'POST',
      headers: releasing ? { 'Content-Type': 'application/json' } : {},
      body: releasing ? JSON.stringify({ stamp: previous.stamp }) : undefined,
      signal: controller.signal,
    })
    const body = await response.json().catch(() => null)
    return interpretHold(response.status, body, releasing, previous)
  } catch {
    return { kind: 'uncertain', stamp: previous?.stamp ?? null }
  } finally { clearTimeout(timer) }
}
