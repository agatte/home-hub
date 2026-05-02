<script>
  import '$lib/styles/global.css'
  import { onMount } from 'svelte'
  import { initStores } from '$lib/stores/init.js'
  import GuestBottomNav from '$lib/components/GuestBottomNav.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  onMount(() => {
    const cleanupStores = initStores()
    return () => { cleanupStores() }
  })
</script>

<div class="guest-shell">
  <slot />
</div>

<GuestBottomNav />

<style>
  .guest-shell {
    min-height: 100vh;
    width: 100%;
    background:
      radial-gradient(circle at 20% 10%, rgba(120, 80, 200, 0.18), transparent 55%),
      radial-gradient(circle at 80% 90%, rgba(220, 130, 90, 0.18), transparent 55%),
      linear-gradient(180deg, #0d0d12 0%, #1a1620 100%);
    color: #f5f3ee;
    font-family: var(--font-body);
    /* Bottom padding leaves room for the fixed GuestBottomNav (~80px including
       safe-area inset on iOS). Anything less and the last card overlaps. */
    padding: 32px 20px calc(96px + env(safe-area-inset-bottom));
    box-sizing: border-box;
  }

  :global(body) {
    margin: 0;
  }
</style>
