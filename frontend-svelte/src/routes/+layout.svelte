<script>
  import '$lib/styles/global.css'
  import { onMount } from 'svelte'
  import { initStores } from '$lib/stores/init.js'
  import { connected } from '$lib/stores/connection.js'
  import Sidebar from '$lib/components/Sidebar.svelte'
  import Header from '$lib/components/Header.svelte'
  import ModeBackground from '$lib/components/ModeBackground.svelte'

  // SvelteKit passes these props to layout components; declaring them
  // silences Svelte's unknown-prop warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  // Mark as used so the linter is happy.
  data; params;

  onMount(() => {
    const cleanup = initStores()
    return cleanup
  })
</script>

<ModeBackground />

<div class="app-shell">
  <Sidebar />
  <div class="app">
    <Header />
    <slot />
    {#if !$connected}
      <div class="reconnect-banner">Reconnecting to server...</div>
    {/if}
  </div>
</div>
