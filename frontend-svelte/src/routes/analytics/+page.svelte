<script>
  import SectorBoard from '$lib/components/sector-board/SectorBoard.svelte'
  import HistoryDrawer from '$lib/components/constellation/HistoryDrawer.svelte'
  import AutonomyGateCard from '$lib/components/AutonomyGateCard.svelte'
  import NarrativeCard from '$lib/components/analytics/NarrativeCard.svelte'
</script>

<svelte:head>
  <title>Analytics · Home Hub</title>
</svelte:head>

<main class="analytics-page">
  <!-- Hero: 8-wedge sector board (live decision pipeline + apartment output) -->
  <SectorBoard />

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
</style>
