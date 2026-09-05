<script>
  import ModeCardDeck from '$lib/components/ModeCardDeck.svelte'
  import ModeIndicator from '$lib/components/ModeIndicator.svelte'
  import RoutineCard from '$lib/components/RoutineCard.svelte'
  import ApartmentWidget from '$lib/components/ApartmentWidget.svelte'
  import SonosCard from '$lib/components/SonosCard.svelte'
  import WeatherCard from '$lib/components/WeatherCard.svelte'
  import PiholeCard from '$lib/components/PiholeCard.svelte'
  import AmbientSoundWidget from '$lib/components/AmbientSoundWidget.svelte'
  import PlantWidget from '$lib/components/PlantWidget.svelte'
  import BarWidget from '$lib/components/BarWidget.svelte'
  import GuestWifiWidget from '$lib/components/GuestWifiWidget.svelte'
  import ActionableWidget from '$lib/components/ActionableWidget.svelte'
  import MusicSuggestionToast from '$lib/components/MusicSuggestionToast.svelte'
  import ModeSuggestionCard from '$lib/components/ModeSuggestionCard.svelte'
  import BrightnessSuggestionCard from '$lib/components/BrightnessSuggestionCard.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  let plantWidget
  let barWidget
  let guestWifiWidget
  let piholeCard
</script>

<main class="home-page">
  <!-- Now Playing strip — full width at top -->
  <section class="widget widget-sonos-strip">
    <SonosCard />
  </section>

  <ModeCardDeck />

  <ModeSuggestionCard />
  <BrightnessSuggestionCard />

  <div class="widget-grid">
    <section class="widget widget-mode">
      <h2 class="widget-title">House &amp; Activity</h2>
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

    <ActionableWidget className="widget-plants" ariaLabel="Open Plants" onActivate={() => plantWidget?.openModal()}>
      <h2 class="widget-title">Plants</h2>
      <PlantWidget cardClickable bind:this={plantWidget} />
    </ActionableWidget>

    <ActionableWidget className="widget-bar" ariaLabel="Open Home Bar" onActivate={() => barWidget?.openModal()}>
      <h2 class="widget-title">Home Bar</h2>
      <BarWidget cardClickable bind:this={barWidget} />
    </ActionableWidget>

    <ActionableWidget className="widget-guest-wifi" ariaLabel="Open Guest WiFi QR" onActivate={() => guestWifiWidget?.openModal()}>
      <h2 class="widget-title">Guests</h2>
      <GuestWifiWidget cardClickable bind:this={guestWifiWidget} />
    </ActionableWidget>

    <ActionableWidget className="widget-pihole" ariaLabel="Open Network Admin" onActivate={() => piholeCard?.openModal()}>
      <h2 class="widget-title">Network</h2>
      <PiholeCard cardClickable bind:this={piholeCard} />
    </ActionableWidget>

    <section class="widget widget-apartment widget-routines-full">
      <h2 class="widget-title">Apartment</h2>
      <ApartmentWidget />
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

  @media (max-width: 480px) {
    .widget-sonos-strip {
      padding: 4px 8px;
    }
  }
</style>
