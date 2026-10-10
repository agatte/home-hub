// Client-side duplicate-attempt fence for the explicit Apple Music control.
// Backend durable event ID and ownership policy remain the true authority.
const attempts = new Map()
const PREFIX = 'homehub:assisted-play:v1:'

export function getAttempt(key) {
  if (attempts.has(key)) return attempts.get(key)
  try {
    const parsed = JSON.parse(globalThis.sessionStorage?.getItem(PREFIX + key) || 'null')
    if (parsed?.clientEventId && typeof parsed.clientEventId === 'string') {
      attempts.set(key, parsed)
      return parsed
    }
  } catch {
    // Storage unavailable: in-memory fence still protects preview remounts.
  }
  return null
}

function remember(key, value) {
  attempts.set(key, value)
  try {
    globalThis.sessionStorage?.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // Never enable retry merely because the browser denied storage.
  }
}

export function reserveAttempt(key, clientEventId) {
  if (getAttempt(key)) return false
  remember(key, { clientEventId, status: 'pending', reason: null })
  return true
}

export function completeAttempt(key, clientEventId, status, reason = null) {
  const current = getAttempt(key)
  if (current?.clientEventId !== clientEventId) return false
  remember(key, { clientEventId, status, reason })
  return true
}

// A separate, deliberate action can allow another session only after checking
// Sonos is neutral. Never reset the registry from a preview or network failure.
export function beginAnotherAttempt(key) {
  const current = getAttempt(key)
  if (!current || current.status === 'pending' || current.status === 'unknown') return false
  attempts.delete(key)
  try { globalThis.sessionStorage?.removeItem(PREFIX + key) } catch {}
  return true
}

export function resetAttemptsForTests() {
  attempts.clear()
}

export function appleMusicTrackId(input) {
  const text = String(input || '').trim()
  if (/^\d{5,20}$/.test(text)) return text
  try {
    const url = new URL(text)
    if (url.protocol !== 'https:' || url.hostname !== 'music.apple.com') return null
    const id = url.searchParams.get('i')
      || (url.pathname.includes('/song/') ? url.pathname.split('/').filter(Boolean).at(-1) : '')
    return /^\d{5,20}$/.test(id || '') ? id : null
  } catch { return null }
}
