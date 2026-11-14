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
    <h1>Control</h1>
    <p class="intro">Browse lighting groups and scenes below. Control is still a read-only preview.</p>
    <a class="live-lighting-link" href="/classic#apartment-controls">
      <span>Adjust lights now</span>
      <span aria-hidden="true">↗</span>
    </a>
    <p class="live-lighting-note">Opens the existing functional HomeHub lighting controls.</p>
  </header>
  <QuietAtlasLightingExperience {routeIntent} />
</main>

<style>
  .quiet-atlas-control { min-height: 100%; padding: 22px 0 40px; color: #eaeae4; background: #101a15; }
  .page-heading { max-width: 1100px; margin: 0 auto; padding: 0 clamp(14px, 4vw, 34px) 8px; }
  h1 { margin: 0; font: normal clamp(34px, 6vw, 48px)/1.1 Georgia, serif; }
  .intro { margin: 10px 0 0; color: #bdc9be; font-size: 14px; line-height: 1.5; }
  .live-lighting-link {
    display: inline-flex; align-items: center; justify-content: space-between; gap: 20px;
    box-sizing: border-box; min-height: 52px; margin-top: 18px; padding: 12px 18px;
    border: 1px solid #9ab49a; border-radius: 14px; background: #e6ebdf;
    color: #17261c; font-size: 15px; font-weight: 700; line-height: 1.35;
    text-decoration: none;
  }
  .live-lighting-link:hover { background: #f2f3e9; }
  .live-lighting-link:focus-visible { outline: 3px solid #d7ebbf; outline-offset: 3px; }
  .live-lighting-note { margin: 8px 0 0; color: #b8c6b8; font-size: 14px; line-height: 1.45; }
  @media (max-width: 600px) {
    .live-lighting-link { display: flex; width: 100%; min-height: 56px; margin-top: 16px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .live-lighting-link { transition: none; }
  }
</style>
