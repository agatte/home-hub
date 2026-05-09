<script>
  import ConstellationView from '$lib/components/constellation/ConstellationView.svelte'
  import HistoryDrawer from '$lib/components/constellation/HistoryDrawer.svelte'
  import AutonomyGateCard from '$lib/components/AutonomyGateCard.svelte'
  import ApartmentOutputCard from '$lib/components/analytics/ApartmentOutputCard.svelte'
  import NarrativeCard from '$lib/components/analytics/NarrativeCard.svelte'
</script>

<svelte:head>
  <title>Analytics · Home Hub</title>
</svelte:head>

<main class="analytics-page">
  <!-- Hero row: live decision pipeline alongside the apartment's current output -->
  <section class="hero">
    <div class="hero-pipeline">
      <ConstellationView />
    </div>
    <div class="hero-output">
      <ApartmentOutputCard />
    </div>
  </section>

  <!-- Slim mode-transition timeline -->
  <HistoryDrawer />

  <!-- Phase 3 autonomy gate: override rate + strategy A/B -->
  <AutonomyGateCard />

  <!-- Daily interpretive narrative — written by the analytics-narrator agent -->
  <NarrativeCard />
</main>

<style>
  .analytics-page {
    padding: 24px 20px 100px;
    max-width: 1280px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* Hero row sits the constellation next to the live-output card.
     Constellation auto-sizes via ResizeObserver, so the grid just gives
     it ~2/3 of the row on desktop. */
  .hero {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
    gap: 20px;
    align-items: stretch;
  }

  .hero-pipeline {
    /* Constellation fills its container — give it a min height so it
       doesn't collapse when the right column is taller. */
    min-height: 520px;
    display: flex;
  }

  .hero-pipeline :global(> *) {
    flex: 1;
    min-width: 0;
  }

  .hero-output {
    display: flex;
  }

  .hero-output :global(> *) {
    flex: 1;
    min-width: 0;
  }

  @media (max-width: 960px) {
    .hero {
      grid-template-columns: minmax(0, 1fr);
    }
    .hero-pipeline {
      min-height: 420px;
    }
  }
</style>
