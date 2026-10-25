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
  return !shouldUseQuietAtlasShell(pathname, searchParams)
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
  if (pathname === '/quiet-atlas/control' || hash === '#control') return 'control'
  if (pathname === '/quiet-atlas' || pathname.startsWith('/quiet-atlas/')) {
    return 'home'
  }
  if (pathname.startsWith('/music')) return 'music'
  if (pathname.startsWith('/analytics')) return 'insights'
  return 'more'
}
