<script>
  import QuietAtlasLightingExperience from '$lib/components/QuietAtlasLightingExperience.svelte'
  import { page } from '$app/stores'
  import { parseControlIntent } from '$lib/quietAtlas/navigation.js'
  $: routeIntent = parseControlIntent($page.url.searchParams)
</script>

<svelte:head>
  <title>Control · Quiet Atlas · HomeHub</title>
  <meta name="description" content="Adjust your lights and apply HomeHub scenes." />
</svelte:head>

<main class="quiet-atlas-control">
  <header class="page-heading">
    <h1>Control</h1>
    <p class="intro">Adjust lights by room, or choose a scene.</p>
  </header>
  <QuietAtlasLightingExperience {routeIntent} functional={true} />
</main>

<style>
  .quiet-atlas-control { min-height: 100%; padding: 22px 0 40px; color: var(--hh-ink, #f1eee7); background: var(--hh-page-background, #121917); }
  .page-heading { max-width: 1100px; margin: 0 auto; padding: 0 clamp(14px, 4vw, 34px) 8px; }
  h1 { margin: 0; font: normal clamp(34px, 6vw, 48px)/1.1 Georgia, serif; }
  .intro { margin: 10px 0 0; color: var(--hh-muted, #bec8c0); font-size: 14px; line-height: 1.5; }
</style>
