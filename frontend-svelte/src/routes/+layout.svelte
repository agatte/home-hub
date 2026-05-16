<script>
  import '$lib/styles/global.css'
  import { onMount } from 'svelte'
  import { page } from '$app/stores'
  import { initStores } from '$lib/stores/init.js'
  import { connectionLost } from '$lib/stores/connection.js'
  import { userIdle, initActivityTracking } from '$lib/stores/activity.js'
  import { initAmbientAudio } from '$lib/ambientAudio.js'
  import ModeBackground from '$lib/components/ModeBackground.svelte'
  import ModeOverlay from '$lib/components/ModeOverlay.svelte'
  import NowPlayingIdle from '$lib/components/NowPlayingIdle.svelte'
  import FloatingNav from '$lib/components/FloatingNav.svelte'
  import NowPlayingChip from '$lib/components/NowPlayingChip.svelte'
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

  // /gameday goes edge-to-edge — the football field is the visual, so the
  // generative ModeBackground is suppressed and the .app container loses
  // its max-width + padding. Other chrome (FloatingNav, VitalStrip,
  // ModeOverlay, NowPlayingChip) stays and layers over the field.
  $: isGamedayRoute = $page.url.pathname === '/gameday'

  onMount(() => {
    const cleanupStores = initStores()
    const cleanupActivity = initActivityTracking()
    const cleanupAmbient = initAmbientAudio()
    return () => { cleanupStores(); cleanupActivity(); cleanupAmbient() }
  })
</script>

{#if !isGuestRoute && !isGamedayRoute}
  <ModeBackground />
{/if}
{#if !isGuestRoute}
  <ModeOverlay />
  <NowPlayingIdle />
{/if}

<div class="app-shell" class:user-idle={$userIdle}>
  <div class:app={!isGamedayRoute} class:app-bleed={isGamedayRoute}>
    <slot />
    {#if $connectionLost && !isGuestRoute}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
  {#if !isGuestRoute}
    <div class="idle-hint">Tap anywhere to wake</div>
  {/if}
</div>

{#if !isGuestRoute}
  <FloatingNav />
  <NowPlayingChip />
  <VitalStrip />
  <!-- Rule-engine mode suggestion toast: cross-route coverage. Self-suppresses
       on / where ModeSuggestionCard owns the banner spot. -->
  <ModeSuggestionToast />
{/if}
<ErrorToast />
