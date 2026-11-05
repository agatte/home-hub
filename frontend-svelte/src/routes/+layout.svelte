<script>
  import '$lib/styles/global.css'
  import { onMount, tick } from 'svelte'
  import { page } from '$app/stores'
  import { initStores } from '$lib/stores/init.js'
  import { initGamedayFeed } from '$lib/stores/gameday.js'
  import { connectionLost } from '$lib/stores/connection.js'
  import { userIdle, initActivityTracking } from '$lib/stores/activity.js'
  import { initAmbientAudio } from '$lib/ambientAudio.js'
  import ModeBackground from '$lib/components/ModeBackground.svelte'
  import ModeOverlay from '$lib/components/ModeOverlay.svelte'
  import NowPlayingIdle from '$lib/components/NowPlayingIdle.svelte'
  import FloatingNav from '$lib/components/FloatingNav.svelte'
  import NowPlayingChip from '$lib/components/NowPlayingChip.svelte'
  import MusicPlayerOverlay from '$lib/components/MusicPlayerOverlay.svelte'
  import ErrorToast from '$lib/components/ErrorToast.svelte'
  import VitalStrip from '$lib/components/VitalStrip.svelte'
  import ModeSuggestionToast from '$lib/components/ModeSuggestionToast.svelte'
  import QuietAtlasShell from '$lib/components/QuietAtlasShell.svelte'
  import QuietAtlasAmbient from '$lib/components/QuietAtlasAmbient.svelte'
  import { AMBIENT_VIEWPORT, ambientRouteEligible } from '$lib/quietAtlas/ambient.js'
  import { shouldUseQuietAtlasShell, shouldShowGlobalErrorToast } from '$lib/quietAtlas/navigation.js'
  import { rootRuntimeTargets } from '$lib/quietAtlas/runtimeRoutePolicy431.js'

  // SvelteKit passes these props to layout components; declaring them
  // silences Svelte's unknown-prop warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  // Mark as used so the linter is happy.
  data; params;

  // /guest is a layout-reset visitor mini-app — strip all kiosk chrome
  // so the only thing the root layout contributes on those paths is the
  // ErrorToast. The guest section owns its own background, padding, and
  // bottom-tab nav via /guest/+layout@.svelte + GuestBottomNav.
  $: isGuestRoute = $page.url.pathname.startsWith('/guest')
  $: isGamedayPrototypeRoute = $page.url.pathname.startsWith('/gameday/prototype')

  // /gameday keeps its edge-to-edge stadium layout and ignores the preview flag.
  $: isGamedayRoute = $page.url.pathname === '/gameday'

  // Quiet Atlas is opt-in: its own route always uses the new shell; existing
  // routes can preview it with ?shell=quiet-atlas without replacing their page.
  // Guest and Game Day keep their purpose-built layouts.
  $: isQuietAtlasShell = shouldUseQuietAtlasShell($page.url.pathname, $page.url.searchParams)
  $: isIsolatedRoute = isGuestRoute || isGamedayPrototypeRoute || isQuietAtlasShell
  let ambientViewport = false
  $: ambientVisible = ambientViewport && ambientRouteEligible($page.url.pathname) && $userIdle

  // Reactive statements run before DOM patching applies inert. The root owns
  // restoration for every dismissal path, including viewport and route changes.
  let wasAmbientVisible = false
  let ambientFocus = null
  $: if (ambientVisible !== wasAmbientVisible) {
    wasAmbientVisible = ambientVisible
    if (ambientVisible) {
      ambientFocus = document.activeElement
    } else {
      const previous = ambientFocus
      ambientFocus = null
      tick().then(() => {
        if (!wasAmbientVisible && previous instanceof HTMLElement &&
            previous.isConnected && !previous.closest('[inert]')) {
          previous.focus({ preventScroll: true })
        }
      })
    }
  }

  onMount(() => {
    let stopViewport = () => {}
    const unsubscribe = page.subscribe(($page) => {
      stopViewport()
      ambientViewport = false
      stopViewport = () => {}
      if (!ambientRouteEligible($page.url.pathname)) return
      const viewport = window.matchMedia(AMBIENT_VIEWPORT)
      const update = () => { ambientViewport = viewport.matches }
      update()
      viewport.addEventListener('change', update)
      stopViewport = () => viewport.removeEventListener('change', update)
    })
    return () => { unsubscribe(); stopViewport() }
  })

  onMount(() => {
    let cleanupStores = null
    let cleanupActivity = null
    let cleanupAmbient = null
    let cleanupGameday = null

    const stopGeneral = () => {
      cleanupStores?.(); cleanupStores = null
      cleanupActivity?.(); cleanupActivity = null
      cleanupAmbient?.(); cleanupAmbient = null
    }
    const startGeneral = () => {
      if (cleanupStores) return
      cleanupStores = initStores()
      cleanupActivity = initActivityTracking()
      cleanupAmbient = initAmbientAudio()
    }
    const stopGameday = () => { cleanupGameday?.(); cleanupGameday = null }

    // Route-owned lifecycle keeps exactly one Game Day feed across client
    // navigation. The fictional #431 artist review must not start or retain
    // HomeHub REST/WebSocket/weather/ambient/activity runtime.
    const unsubscribe = page.subscribe(($page) => {
      const { general, gameday } = rootRuntimeTargets($page.url.pathname)
      if (gameday) {
        if (!cleanupGameday) cleanupGameday = initGamedayFeed()
      } else stopGameday()

      if (general) startGeneral()
      else stopGeneral()
    })

    return () => { unsubscribe(); stopGeneral(); stopGameday() }
  })
</script>

{#if !isIsolatedRoute && !isGamedayRoute}
  <ModeBackground />
{/if}
{#if !isIsolatedRoute}
  <ModeOverlay />
  <NowPlayingIdle />
{/if}

<div class="app-shell" class:user-idle={$userIdle && !isQuietAtlasShell} inert={ambientVisible}>
  <div
    class:app={!isGamedayRoute && !isGamedayPrototypeRoute && !isQuietAtlasShell}
    class:app-bleed={isGamedayRoute || isGamedayPrototypeRoute}
  >
    {#if isQuietAtlasShell}
      <QuietAtlasShell>
        <slot />
      </QuietAtlasShell>
    {:else}
      <slot />
    {/if}
    {#if $connectionLost && !isIsolatedRoute}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
  {#if !isIsolatedRoute}
    <div class="idle-hint">Tap anywhere to wake</div>
  {/if}
</div>

{#if ambientVisible}
  <QuietAtlasAmbient />
{/if}

{#if !isIsolatedRoute}
  <FloatingNav />
  <NowPlayingChip />
  <MusicPlayerOverlay />
  <VitalStrip />
  <!-- Rule-engine mode suggestion toast: cross-route coverage. Self-suppresses
       on / where ModeSuggestionCard owns the banner spot. -->
  <ModeSuggestionToast />
{/if}
{#if shouldShowGlobalErrorToast($page.url.pathname, $page.url.searchParams)}
  <ErrorToast />
{/if}
