<script>
  import { onMount } from 'svelte'
  import { goto } from '$app/navigation'
  import { classicBookmarkHref } from '$lib/quietAtlas/navigation.js'

  let destination = '/'

  // The app is a static SPA. Replace the retired route in browser history
  // and provide an ordinary same-origin link if client navigation fails.
  onMount(() => {
    destination = classicBookmarkHref(window.location.hash)
    void goto(destination, { replaceState: true }).catch(() => {})
  })
</script>

<svelte:head><title>HomeHub</title></svelte:head>

<main class="bookmark" aria-label="HomeHub moved">
  <h1>HomeHub has moved</h1>
  <p>All owner controls are now in the redesigned HomeHub.</p>
  <a href={destination}>Continue to HomeHub</a>
</main>

<style>
  .bookmark {max-width:560px;margin:clamp(32px,8vw,96px) auto;padding:24px;display:grid;gap:16px;color:var(--hh-ink);}
  h1 {font:500 clamp(28px,5vw,42px)/1.15 var(--hh-display);}
  p {color:var(--hh-muted);}
  a {display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:8px 16px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);color:var(--hh-ink);background:var(--hh-control);}
  a:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
</style>
