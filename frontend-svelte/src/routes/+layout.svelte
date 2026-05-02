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

  // SvelteKit passes these props to layout components; declaring them
  // silences Svelte's unknown-prop warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  // Mark as used so the linter is happy.
  data; params;

  // /guest is a kiosk landing for visitors — no nav, no music chip.
  $: isGuestRoute = $page.url.pathname.startsWith('/guest')

  onMount(() => {
    const cleanupStores = initStores()
    const cleanupActivity = initActivityTracking()
    const cleanupAmbient = initAmbientAudio()
    return () => { cleanupStores(); cleanupActivity(); cleanupAmbient() }
  })
</script>

<ModeBackground />
<ModeOverlay />
<NowPlayingIdle />

<div class="app-shell" class:user-idle={$userIdle}>
  <div class="app">
    <slot />
    {#if $connectionLost}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
  <div class="idle-hint">Tap anywhere to wake</div>
</div>

{#if !isGuestRoute}
  <FloatingNav />
  <NowPlayingChip />
{/if}
<ErrorToast />
<VitalStrip />
