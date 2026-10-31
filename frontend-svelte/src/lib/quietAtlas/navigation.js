import { LIGHTING_GROUPS } from './lightingModel.js'

const controlGroupIds = new Set(LIGHTING_GROUPS.map(({ id }) => id))
export const CONTROL_SCENES_HREF = '/quiet-atlas/control?view=scenes'

/** Return only navigation destinations for known, display-only fixture groups. */
export function controlGroupHref(groupId) {
  return controlGroupIds.has(groupId)
    ? `/quiet-atlas/control?group=${encodeURIComponent(groupId)}`
    : '/quiet-atlas/control'
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
    href: '/settings',
    shell: true,
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
  return !(pathname === '/quiet-atlas' || pathname.startsWith('/quiet-atlas/'))
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

export function activeQuietAtlasSection(pathname, hash = '') {
  if (pathname === '/quiet-atlas' || pathname === '/quiet-atlas/control' || hash === '#control') return 'control'
  if (pathname === '/quiet-atlas/home' || pathname.startsWith('/quiet-atlas/')) return 'home'
  if (pathname.startsWith('/music')) return 'music'
  if (pathname.startsWith('/analytics')) return 'insights'
  return 'more'
}
