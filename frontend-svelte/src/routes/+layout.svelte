<script>
  import '$lib/styles/global.css'
  import { onMount } from 'svelte'
  import { initStores } from '$lib/stores/init.js'
  import { connected } from '$lib/stores/connection.js'
  import { userIdle, initActivityTracking } from '$lib/stores/activity.js'
  import ModeBackground from '$lib/components/ModeBackground.svelte'
  import ModeOverlay from '$lib/components/ModeOverlay.svelte'
  import FloatingNav from '$lib/components/FloatingNav.svelte'
  import NowPlayingChip from '$lib/components/NowPlayingChip.svelte'

  // SvelteKit passes these props to layout components; declaring them
  // silences Svelte's unknown-prop warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  // Mark as used so the linter is happy.
  data; params;

  onMount(() => {
    const cleanupStores = initStores()
    const cleanupActivity = initActivityTracking()
    return () => { cleanupStores(); cleanupActivity() }
  })
</script>

<ModeBackground />
<ModeOverlay />

<div class="app-shell" class:user-idle={$userIdle}>
  <div class="app">
    <slot />
    {#if !$connected}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
  <div class="idle-hint">Tap anywhere to wake</div>
</div>

<FloatingNav />
<NowPlayingChip />
