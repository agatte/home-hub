<script>
  import TasteProfileCard from '$lib/components/TasteProfileCard.svelte'
  import ModePlaylistMapper from '$lib/components/ModePlaylistMapper.svelte'
  import RecommendationPanel from '$lib/components/RecommendationPanel.svelte'
  import ShadowDiscoveryPanel from '$lib/components/ShadowDiscoveryPanel.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;
</script>

<main class="music-page">
  <div class="page-grid">
    <section class="widget">
      <h2 class="widget-title">Taste Profile</h2>
      <TasteProfileCard />
    </section>

    <section class="widget">
      <h2 class="widget-title">Mode → Playlist</h2>
      <ModePlaylistMapper />
    </section>

    <section class="widget widget-full discovery-lab-wrap">
      <ShadowDiscoveryPanel />
    </section>

    <section class="widget widget-full">
      <h2 class="widget-title">Discover</h2>
      <RecommendationPanel />
    </section>
  </div>
</main>

<style>
  .music-page {
    padding-top: 4px;
  }

  .page-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 20px;
  }

  .widget-full {
    grid-column: 1 / -1;
  }

  .discovery-lab-wrap {
    padding: 0;
    overflow: hidden;
  }

  @media (max-width: 900px) {
    .page-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
