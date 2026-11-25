<script>
  import ListeningChoices from '$lib/components/ListeningChoices.svelte'
  import QuietAtlasNowPlaying from '$lib/components/QuietAtlasNowPlaying.svelte'
  import TasteProfileCard from '$lib/components/TasteProfileCard.svelte'
  import ModePlaylistMapper from '$lib/components/ModePlaylistMapper.svelte'
  import ShadowDiscoveryPanel from '$lib/components/ShadowDiscoveryPanel.svelte'
  import ApprovedAppleMusicEntry from '$lib/components/ApprovedAppleMusicEntry.svelte'
  import PrepareSonosAction from '$lib/components/PrepareSonosAction.svelte'
  import MusicBanditDiagnostics from '$lib/components/MusicBanditDiagnostics.svelte'

  /** @type {{ provider_id: string } | null} */
  let selectedAppleTrack = null
  let advancedOpen = false

  /** @param {string} providerId */
  function reviewAppleTrack(providerId) {
    selectedAppleTrack = { provider_id: providerId }
  }
</script>

<main class="music-page" aria-label="HomeHub Music">
  <header class="music-heading">
    <p>HOMEHUB / LISTEN</p>
    <h1>Music</h1>
    <span>What’s playing, what fits your moment, and what you want to hear next.</span>
  </header>
  <ListeningChoices />
  <QuietAtlasNowPlaying />
  <nav class="music-jump" aria-label="Music sections">
    <a href="#music-discover" on:click={() => advancedOpen = true}>Advanced discovery &amp; playback</a>
    <a href="#music-manage">Library &amp; preferences</a>
  </nav>
  <details class="music-manage music-primary" id="music-discover" bind:open={advancedOpen}>
    <summary><span><strong>Advanced listening tools</strong><small>Track review, exact playback and discovery diagnostics</small></span><span class="manage-action">Open</span></summary>
    <ShadowDiscoveryPanel onReviewAppleTrack={reviewAppleTrack} />

  {#if selectedAppleTrack}
    <p class="music-handoff" role="status">
      Discovery track selected for review only.
      <a href="#approved-apple-track">Review its exact Apple Music identity below</a>
      before separately approving or starting playback.
    </p>
  {/if}
  <PrepareSonosAction />
  <ApprovedAppleMusicEntry selectedTrack={selectedAppleTrack} />
  </details>

  <details class="music-manage" id="music-manage">
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

  <details class="music-manage">
    <summary><span><strong>Listening insights</strong><small>Learning and recommendation diagnostics</small></span><span class="manage-action">Open</span></summary>
    <MusicBanditDiagnostics />
  </details>
  <details class="music-preview">
    <summary>Experimental design studies</summary>
    <a href="/quiet-atlas/music/artist-review">Preview fictional artist matching</a>
    <p>Session-only fictional review; no Apple history or catalog requests.</p>
  </details>
</main>

<style>
  .music-page {
    display: flex;
    flex-direction: column;
    gap: 20px;
    padding: clamp(18px, 3vw, 42px) var(--hh-gutter, 16px) 44px;
    max-width: 1400px;
    margin: 0 auto;
    min-width: 0;
    color: var(--hh-ink);
    --bg-primary: var(--hh-panel-deep);
    --bg-secondary: var(--hh-panel);
    --bg-card: var(--hh-card-background);
    --bg-card-hover: var(--hh-control-hover);
    --text-primary: var(--hh-ink);
    --text-secondary: var(--hh-muted);
    --text-muted: var(--hh-muted);
    --accent: var(--hh-accent);
    --border: var(--hh-line);
    --radius: var(--hh-radius-panel);
    --radius-sm: var(--hh-radius-control);
    --font-body: var(--hh-font);
  }

  .music-heading {display:grid;gap:7px;}
  .music-heading p {color:var(--hh-accent);font-size:11px;font-weight:700;letter-spacing:.14em;}
  .music-heading h1 {font:500 clamp(36px,5vw,60px)/1.1 var(--hh-display);letter-spacing:-.04em;}
  .music-heading span {color:var(--hh-muted);font-size:14px;line-height:1.5;}
  .music-jump {display:flex;flex-wrap:wrap;gap:8px;}
  .music-jump a,.music-preview a {display:inline-flex;align-items:center;min-height:44px;padding:8px 14px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);color:var(--hh-ink);text-decoration:none;background:var(--hh-control);font-size:13px;}
  .music-jump a:hover,.music-preview a:hover {background:var(--hh-control-hover);}
  .music-jump a:focus-visible,.music-preview a:focus-visible,.music-manage summary:focus-visible,.music-preview summary:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
  .music-preview {padding:14px 16px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-panel);color:var(--hh-muted);}
  .music-preview summary {min-height:44px;cursor:pointer;display:list-item;padding:10px 0;}
  .music-preview p {font-size:12px;margin-top:8px;}
  .music-primary {
    min-width: 0;
  }
  .music-handoff {
    max-width: 1240px;
    margin: 0;
    color: var(--text-primary);
    font-size: 12px;
  }
  .music-handoff a { color: var(--accent); }

  .music-manage {
    max-width: 1240px;
    width: calc(100% - 8px);
    margin: 0 auto;
    border: 1px solid var(--hh-line);
    border-radius: var(--hh-radius-panel);
    padding: 0 16px;
    background: var(--hh-card-background);
  }

  .music-manage > summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 18px 4px;
    min-height: 56px;
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

  @media (max-width: 600px) {
    .music-page {gap:16px;padding:18px 16px 32px;}
    .music-jump a {flex:1 1 auto;justify-content:center;}
    .music-page :global(button:not(.icon-button)),.music-page :global(select) {min-height:44px;}
    .music-page :global(.widget) {min-width:0;}
  }
  @media (max-width: 900px) {
    .management-grid { grid-template-columns: minmax(0, 1fr); }
    .music-manage > summary { align-items: flex-start; }
  }
</style>
