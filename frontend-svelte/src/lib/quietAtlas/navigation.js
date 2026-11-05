import { LIGHTING_GROUPS } from './lightingModel.js'

// 'other' is a read-only group created only when the API reports extra fixtures.
// This allowlist grants a display route, never device write authority.
const controlGroupIds = new Set([...LIGHTING_GROUPS.map(({ id }) => id), 'other'])
export const CONTROL_SCENES_HREF = '/quiet-atlas/control?view=scenes'

/** Whether a route refers to an approved display-only lighting group. */
export function isKnownLightingGroup(groupId) {
  return typeof groupId === 'string' && controlGroupIds.has(groupId)
}

/** A focused, non-modal detail destination. Origin is an allowlisted tab, not a redirect. */
export function lightingDetailHref(groupId, from = 'control') {
  const origin = from === 'home' ? 'home' : 'control'
  return isKnownLightingGroup(groupId)
    ? `/quiet-atlas/lighting/${encodeURIComponent(groupId)}?from=${origin}`
    : `/quiet-atlas/${origin}`
}

/** Direct/bookmarked links have a deterministic safe return destination. */
export function lightingDetailOrigin(searchParams) {
  return searchParams?.get('from') === 'home' ? 'home' : 'control'
}

/** Existing callers now receive the same non-modal detail destination. */
export function controlGroupHref(groupId) {
  return lightingDetailHref(groupId, 'control')
}

/** Validate exactly one read-only detail target, never an arbitrary scene or device command. */
export function parseControlIntent(searchParams) {
  if (!searchParams || typeof searchParams.getAll !== 'function') return null
  const groups = searchParams.getAll('group')
  const views = searchParams.getAll('view')
  if (groups.length + views.length !== 1) return null
  if (groups.length === 1 && controlGroupIds.has(groups[0])) return `group:${groups[0]}`
  if (views.length === 1 && views[0] === 'scenes') return 'scenes'
  return null
}

export const MORE_DESTINATIONS = [
  {
    id: 'settings',
    label: 'Settings',
    description: 'Automation, schedules, modes, and integrations.',
    href: '/quiet-atlas/settings',
    shell: false,
  },
  {
    id: 'journal',
    label: 'Activity journal',
    description: 'History and nightly summaries.',
    href: '/journal',
    shell: true,
  },
  {
    id: 'personality',
    label: 'Personalization',
    description: 'Mood, preferences, and learning tools.',
    href: '/personality',
    shell: true,
  },
  {
    id: 'apartment',
    label: 'Apartment and household tools',
    description: 'The current Home page keeps the Apartment widget, plants, bar, Guest Wi-Fi, routines, and ambient controls.',
    href: '/',
    shell: false,
  },
  {
    id: 'gameday',
    label: 'Game Day',
    description: 'The existing edge-to-edge stadium experience.',
    href: '/gameday',
    shell: false,
  },
  {
    id: 'guest',
    label: 'Guest experience',
    description: 'Visitor Wi-Fi and guest-specific tools.',
    href: '/guest',
    shell: false,
  },
]

// Only explicitly enumerated, read-only review routes may suppress global error toasts.
// Future functional routes fail open to the normal error display.
const READ_ONLY_PREVIEW_PATHS = new Set([
  '/quiet-atlas', '/quiet-atlas/home', '/quiet-atlas/control',
  '/quiet-atlas/insights', '/quiet-atlas/settings', '/quiet-atlas/music',
  '/quiet-atlas/music/artist-review',
])

/** @param {string} pathname */
export function isQuietAtlasReadOnlyPreview(pathname) {
  const match = /^\/quiet-atlas\/lighting\/([^/]+)$/.exec(pathname)
  return READ_ONLY_PREVIEW_PATHS.has(pathname) || (match !== null && isKnownLightingGroup(match[1]))
}

export function shouldUseQuietAtlasShell(pathname, searchParams) {
  if (pathname === '/quiet-atlas' || pathname.startsWith('/quiet-atlas/')) return true
  if (pathname === '/gameday' || pathname.startsWith('/gameday/') ||
      pathname === '/guest' || pathname.startsWith('/guest/')) return false
  return searchParams?.get('shell') === 'quiet-atlas'
}

export function shouldShowGlobalErrorToast(pathname, searchParams) {
  if (pathname.startsWith('/gameday/prototype')) return false
  // Only the isolated, read-only Quiet Atlas previews suppress global error toasts.
  // Functional opt-in Music, Insights, and Settings must retain failure visibility.
  return !isQuietAtlasReadOnlyPreview(pathname)
}

export function withQuietAtlasShell(href) {
  const hashAt = href.indexOf('#')
  const hash = hashAt >= 0 ? href.slice(hashAt) : ''
  let base = hashAt >= 0 ? href.slice(0, hashAt) : href
  const existing = /([?&])shell=[^&]*/
  if (existing.test(base)) {
    base = base.replace(existing, '$1shell=quiet-atlas')
  } else {
    base += (base.includes('?') ? '&' : '?') + 'shell=quiet-atlas'
  }
  return base + hash
}

// Route identity outranks an arbitrary fragment. A Music/Settings #control anchor
// must not highlight the Control destination in the shared preview shell.
/** @param {URLSearchParams | null} [searchParams] */
export function activeQuietAtlasSection(pathname, _hash = '', searchParams = null) {
  if (pathname.startsWith('/quiet-atlas/lighting/')) return lightingDetailOrigin(searchParams)
  if (pathname === '/quiet-atlas' || pathname === '/quiet-atlas/control') return 'control'
  if (pathname === '/quiet-atlas/insights') return 'insights'
  if (pathname === '/quiet-atlas/settings') return 'more'
  if (pathname === '/quiet-atlas/music' || pathname.startsWith('/quiet-atlas/music/')) return 'music'
  if (pathname === '/quiet-atlas/home' || pathname.startsWith('/quiet-atlas/')) return 'home'
  if (pathname.startsWith('/music')) return 'music'
  if (pathname.startsWith('/analytics')) return 'insights'
  return 'more'
}
