<script>
  import ModeCardDeck from '$lib/components/ModeCardDeck.svelte'
  import ModeIndicator from '$lib/components/ModeIndicator.svelte'
  import RoutineCard from '$lib/components/RoutineCard.svelte'
  import LightGrid from '$lib/components/LightGrid.svelte'
  import SceneBrowser from '$lib/components/SceneBrowser.svelte'
  import SonosCard from '$lib/components/SonosCard.svelte'
  import WeatherCard from '$lib/components/WeatherCard.svelte'
  import PiholeCard from '$lib/components/PiholeCard.svelte'
  import AmbientSoundWidget from '$lib/components/AmbientSoundWidget.svelte'
  import PlantWidget from '$lib/components/PlantWidget.svelte'
  import BarWidget from '$lib/components/BarWidget.svelte'
  import MusicSuggestionToast from '$lib/components/MusicSuggestionToast.svelte'
  import ModeSuggestionToast from '$lib/components/ModeSuggestionToast.svelte'

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

  <ModeCardDeck />

  <div class="widget-grid">
    <section class="widget widget-mode">
      <h2 class="widget-title">Mode</h2>
      <ModeIndicator />
    </section>

    <section class="widget widget-weather">
      <h2 class="widget-title">Weather</h2>
      <WeatherCard />
    </section>

    <section class="widget widget-ambient">
      <h2 class="widget-title">Ambient</h2>
      <AmbientSoundWidget />
    </section>

    <section class="widget widget-plants">
      <h2 class="widget-title">Plants</h2>
      <PlantWidget />
    </section>

    <section class="widget widget-bar">
      <h2 class="widget-title">Home Bar</h2>
      <BarWidget />
    </section>

    <section class="widget widget-pihole">
      <h2 class="widget-title">Network</h2>
      <PiholeCard />
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
  <ModeSuggestionToast />
</main>

<style>
  .widget-sonos-strip {
    margin-bottom: 8px;
    padding: 8px 12px;
  }

  @media (max-width: 480px) {
    .widget-sonos-strip {
      padding: 4px 8px;
    }
  }
</style>
