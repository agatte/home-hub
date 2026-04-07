<script>
  import TasteProfileCard from '$lib/components/TasteProfileCard.svelte'
  import ModePlaylistMapper from '$lib/components/ModePlaylistMapper.svelte'
  import RecommendationPanel from '$lib/components/RecommendationPanel.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;
</script>

<main class="music-page">
  <section class="section">
    <h2 class="section-title">Taste Profile</h2>
    <TasteProfileCard />
  </section>

  <section class="section">
    <h2 class="section-title">Mode → Playlist Mapping</h2>
    <ModePlaylistMapper />
  </section>

  <section class="section">
    <h2 class="section-title">Discover</h2>
    <RecommendationPanel />
  </section>
</main>
