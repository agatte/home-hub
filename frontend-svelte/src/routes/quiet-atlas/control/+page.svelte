<script>
  import QuietAtlasLightingExperience from '$lib/components/QuietAtlasLightingExperience.svelte'
  import { page } from '$app/stores'
  import { parseControlIntent } from '$lib/quietAtlas/navigation.js'
  $: routeIntent = parseControlIntent($page.url.searchParams)
</script>

<svelte:head>
  <title>Control · Quiet Atlas · HomeHub</title>
  <meta name="description" content="Browse HomeHub lighting groups and scenes in the read-only Quiet Atlas design preview." />
</svelte:head>

<main class="quiet-atlas-control">
  <header class="page-heading">
    <p class="eyebrow">QUIET ATLAS · APARTMENT</p>
    <h1>Control</h1>
    <p class="intro">Lighting groups, individual fixtures, and scene library.</p>
  </header>
  <QuietAtlasLightingExperience {routeIntent} />
</main>

<style>
  .quiet-atlas-control { min-height: 100%; padding: 22px 0 40px; color: #eaeae4; background: #101a15; }
  .page-heading { max-width: 1100px; margin: 0 auto; padding: 0 clamp(14px, 4vw, 34px) 8px; }
  .eyebrow { margin: 0 0 8px; color: #9fb3a1; font-size: 11px; font-weight: 700; letter-spacing: .14em; }
  h1 { margin: 0; font: normal clamp(34px, 6vw, 48px)/1.1 Georgia, serif; }
  .intro { margin: 10px 0 0; color: #bdc9be; font-size: 14px; line-height: 1.5; }
</style>
