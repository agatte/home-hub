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
  import MusicPlayerOverlay from '$lib/components/MusicPlayerOverlay.svelte'
  import ErrorToast from '$lib/components/ErrorToast.svelte'
  import VitalStrip from '$lib/components/VitalStrip.svelte'
  import ModeSuggestionToast from '$lib/components/ModeSuggestionToast.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  $: isGuestRoute = $page.url.pathname.startsWith('/guest')

  // Home now owns House State + Activity context in-flow. Keep the legacy
  // fixed overlay on secondary routes until later #157 shell migration.
  $: isHomeRoute = $page.url.pathname === '/'

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
{#if !isGuestRoute && !isHomeRoute}
  <ModeOverlay />
{/if}
{#if !isGuestRoute}
  <NowPlayingIdle />
{/if}

<div class="app-shell" class:user-idle={$userIdle}>
  <div
    class:app={!isGamedayRoute}
    class:app-home={isHomeRoute && !isGamedayRoute}
    class:app-bleed={isGamedayRoute}
  >
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
  <MusicPlayerOverlay />
  <VitalStrip />
  <ModeSuggestionToast />
{/if}
<ErrorToast />
