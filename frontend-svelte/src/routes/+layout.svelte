<script>
  import '$lib/styles/global.css'
  import { onMount } from 'svelte'
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
  $: isIsolatedRoute = isGuestRoute || isGamedayPrototypeRoute

  // /gameday goes edge-to-edge — the football field is the visual, so the
  // generative ModeBackground is suppressed and the .app container loses
  // its max-width + padding. Other chrome (FloatingNav, VitalStrip,
  // ModeOverlay, NowPlayingChip) stays and layers over the field.
  $: isGamedayRoute = $page.url.pathname === '/gameday'

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
    // navigation. The prototype remains isolated from unrelated kiosk stores.
    const unsubscribe = page.subscribe(($page) => {
      const path = $page.url.pathname
      const guest = path.startsWith('/guest')
      const gamedayPath = path === '/gameday' || path.startsWith('/gameday/prototype')
      if (guest) { stopGeneral(); stopGameday(); return }

      if (gamedayPath && !cleanupGameday) cleanupGameday = initGamedayFeed()
      if (!gamedayPath) stopGameday()

      if (path.startsWith('/gameday/prototype')) stopGeneral()
      else startGeneral()
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

<div class="app-shell" class:user-idle={$userIdle}>
  <div class:app={!isGamedayRoute && !isGamedayPrototypeRoute} class:app-bleed={isGamedayRoute || isGamedayPrototypeRoute}>
    <slot />
    {#if $connectionLost && !isIsolatedRoute}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
  {#if !isIsolatedRoute}
    <div class="idle-hint">Tap anywhere to wake</div>
  {/if}
</div>

{#if !isIsolatedRoute}
  <FloatingNav />
  <NowPlayingChip />
  <MusicPlayerOverlay />
  <VitalStrip />
  <!-- Rule-engine mode suggestion toast: cross-route coverage. Self-suppresses
       on / where ModeSuggestionCard owns the banner spot. -->
  <ModeSuggestionToast />
{/if}
{#if !isGamedayPrototypeRoute}
  <ErrorToast />
{/if}
