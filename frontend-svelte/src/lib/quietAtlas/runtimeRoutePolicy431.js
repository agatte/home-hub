/**
 * Route-scoped root runtime targets.
 *
 * The #431 artist review is a fixture-only surface. It must not bootstrap
 * general HomeHub REST/WebSocket/weather/ambient/activity runtime, including
 * when reached through client navigation. Do not broaden this exception to
 * functional Quiet Atlas Music or other dashboard routes.
 *
 * Pure decision only; +layout.svelte owns starting and cleaning up services.
 * @param {string} pathname
 * @returns {{ general: boolean, gameday: boolean }}
 */
export function rootRuntimeTargets(pathname) {
  if (typeof pathname !== 'string') return { general: false, gameday: false }
  if (pathname.startsWith('/guest') ||
      pathname === '/quiet-atlas/music/artist-review') {
    return { general: false, gameday: false }
  }

  const prototype = pathname.startsWith('/gameday/prototype')
  return {
    general: !prototype,
    gameday: pathname === '/gameday' || prototype,
  }
}
