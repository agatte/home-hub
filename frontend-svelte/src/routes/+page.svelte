<script>
  import QuickActions from '$lib/components/QuickActions.svelte'
  import ModeIndicator from '$lib/components/ModeIndicator.svelte'
  import ModeOverrideBar from '$lib/components/ModeOverrideBar.svelte'
  import RoutineCard from '$lib/components/RoutineCard.svelte'
  import LightGrid from '$lib/components/LightGrid.svelte'
  import SceneBrowser from '$lib/components/SceneBrowser.svelte'
  import SonosCard from '$lib/components/SonosCard.svelte'
  import MusicSuggestionToast from '$lib/components/MusicSuggestionToast.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;
</script>

<main class="home-page">
  <!-- Now Playing strip — full width at top -->
  <section class="widget widget-sonos-strip">
    <SonosCard />
  </section>

  <QuickActions />

  <div class="widget-grid">
    <section class="widget widget-mode">
      <h2 class="widget-title">Mode</h2>
      <ModeIndicator />
      <ModeOverrideBar />
    </section>

    <section class="widget widget-lights">
      <h2 class="widget-title">Lights</h2>
      <LightGrid />
    </section>

    <section class="widget widget-scenes widget-routines-full">
      <h2 class="widget-title">Scenes</h2>
      <SceneBrowser />
    </section>

    <section class="widget widget-routines widget-routines-full">
      <h2 class="widget-title">Routines</h2>
      <RoutineCard />
    </section>
  </div>

  <MusicSuggestionToast />
</main>

<style>
  .widget-sonos-strip {
    margin-bottom: 8px;
    padding: 8px 12px;
  }
</style>
