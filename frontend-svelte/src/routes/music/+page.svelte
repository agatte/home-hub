<script>
  import TasteProfileCard from '$lib/components/TasteProfileCard.svelte'
  import ModePlaylistMapper from '$lib/components/ModePlaylistMapper.svelte'
  import ShadowDiscoveryPanel from '$lib/components/ShadowDiscoveryPanel.svelte'

  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;
</script>

<main class="music-page">
  <section class="music-primary">
    <ShadowDiscoveryPanel />
  </section>

  <details class="music-manage">
    <summary>
      <span>
        <strong>Manage music</strong>
        <small>Library profile, imports, and manual mode-to-playlist mappings</small>
      </span>
      <span class="manage-action">Open</span>
    </summary>
    <div class="management-grid">
      <section class="widget">
        <h2 class="widget-title">Taste Profile</h2>
        <TasteProfileCard />
      </section>
      <section class="widget">
        <h2 class="widget-title">Manual Playlist Mapping</h2>
        <ModePlaylistMapper />
      </section>
    </div>
  </details>
</main>

<style>
  .music-page {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: 4px 0 28px;
  }

  .music-primary {
    min-width: 0;
  }

  .music-manage {
    max-width: 1240px;
    width: calc(100% - 8px);
    margin: 0 auto;
    border-top: 1px solid var(--border);
  }

  .music-manage > summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 18px 4px;
    cursor: pointer;
    list-style: none;
  }

  .music-manage > summary::-webkit-details-marker { display: none; }
  .music-manage > summary > span:first-child { display: flex; flex-direction: column; gap: 4px; }
  .music-manage strong { color: var(--text-primary); font-size: 13px; }
  .music-manage small { color: var(--text-muted); font-size: 10px; }
  .manage-action { color: var(--accent); font-size: 11px; }
  .music-manage[open] .manage-action { font-size: 0; }
  .music-manage[open] .manage-action::after { content: 'Close'; font-size: 11px; }

  .management-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    padding: 0 0 8px;
  }

  @media (max-width: 900px) {
    .management-grid { grid-template-columns: minmax(0, 1fr); }
    .music-manage > summary { align-items: flex-start; }
  }
</style>
