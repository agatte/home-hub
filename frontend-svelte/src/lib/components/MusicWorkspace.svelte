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
  let toolsOpen = false

  /** @param {string} providerId */
  function reviewAppleTrack(providerId) {
    selectedAppleTrack = { provider_id: providerId }
  }
</script>

<main class="music-page" aria-label="HomeHub Music">
  <header class="music-heading">
    <div class="heading-copy">
    <p>HOMEHUB / LISTEN</p>
    <h1>Music</h1>
    <span>Make the moment yours.</span>
    </div>
    <a class="tools-link" href="#music-tools" on:click={() => toolsOpen = true}>Library &amp; preferences <span aria-hidden="true">&rarr;</span></a>
  </header>
  <div class="listening-room">
    <QuietAtlasNowPlaying />
    <ListeningChoices />
  </div>
  <details class="tools-drawer" id="music-tools" bind:open={toolsOpen}>
    <summary><span><strong>Your music, behind the scenes</strong><small>Library, preferences and advanced listening tools</small></span><span class="manage-action">Open</span></summary>
    <div class="tools-body">
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
    </div>
  </details>
</main>

<style>
  .music-page {
    display:grid;gap:clamp(22px,3vw,38px);padding:clamp(18px,3vw,42px) var(--hh-gutter,16px) 44px;
    max-width:1480px;margin:0 auto;min-width:0;color:var(--hh-ink);
    --bg-primary:var(--hh-panel-deep);--bg-secondary:var(--hh-panel);--bg-card:var(--hh-card-background);
    --bg-card-hover:var(--hh-control-hover);--text-primary:var(--hh-ink);--text-secondary:var(--hh-muted);
    --text-muted:var(--hh-muted);--accent:var(--hh-accent);--border:var(--hh-line);
    --radius:var(--hh-radius-panel);--radius-sm:var(--hh-radius-control);--font-body:var(--hh-font);
  }
  .music-heading {display:flex;align-items:flex-end;justify-content:space-between;gap:14px;flex-wrap:wrap;}
  .heading-copy {display:grid;gap:7px;}
  .heading-copy p {color:var(--hh-accent);font-size:11px;font-weight:700;letter-spacing:.14em;}
  .heading-copy h1 {font:500 clamp(38px,5vw,66px)/1.05 var(--hh-display);letter-spacing:-.045em;}
  .heading-copy span {color:var(--hh-muted);font-size:14px;line-height:1.5;}
  .tools-link,.music-preview a {display:inline-flex;align-items:center;gap:12px;min-height:44px;color:var(--hh-accent);text-decoration:none;font-size:13px;font-weight:650;}
  .tools-link:hover,.music-preview a:hover {text-decoration:underline;}
  .listening-room {display:grid;grid-template-columns:minmax(0,.88fr) minmax(0,1.3fr);align-items:start;gap:clamp(16px,2.6vw,32px);min-width:0;}
  .tools-drawer {min-width:0;scroll-margin-top:20px;border-top:1px solid var(--hh-line);border-bottom:1px solid var(--hh-line);}
  .tools-drawer > summary,.music-manage > summary {display:flex;align-items:center;justify-content:space-between;gap:14px;padding:18px 4px;min-height:56px;cursor:pointer;list-style:none;}
  .tools-drawer > summary::-webkit-details-marker,.music-manage > summary::-webkit-details-marker {display:none;}
  .tools-drawer > summary > span:first-child,.music-manage > summary > span:first-child {display:grid;gap:5px;min-width:0;}
  .tools-drawer strong {color:var(--hh-ink);font-size:15px;font-weight:650;}
  .tools-drawer small {color:var(--hh-muted);font-size:12px;line-height:1.45;}
  .tools-body {display:grid;gap:10px;padding:0 0 16px;min-width:0;}
  .music-manage,.music-preview {border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);padding:0 16px;background:var(--hh-card-background);min-width:0;}
  .music-manage strong {font-size:13px;}
  .music-manage small {font-size:11px;}
  .manage-action {color:var(--hh-accent);font-size:12px;flex-shrink:0;}
  .tools-drawer[open] > summary .manage-action,.music-manage[open] > summary .manage-action {font-size:0;}
  .tools-drawer[open] > summary .manage-action::after,.music-manage[open] > summary .manage-action::after {content:'Close';font-size:12px;}
  .music-preview {color:var(--hh-muted);}
  .music-preview summary {min-height:44px;cursor:pointer;padding:10px 0;}
  .music-preview p {font-size:12px;margin:0 0 14px;}
  .music-handoff {color:var(--text-primary);font-size:12px;line-height:1.5;}
  .music-handoff a {color:var(--accent);}
  .management-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;padding:0 0 8px;}
  .tools-link:focus-visible,.music-preview a:focus-visible,.tools-drawer summary:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
  @media(max-width:1050px) {.listening-room{grid-template-columns:minmax(0,1fr);}}
  @media(max-width:900px) {.management-grid{grid-template-columns:minmax(0,1fr);}}
  @media(max-width:600px) {
    .music-page{gap:22px;padding:18px 16px 32px;}
    .music-heading{align-items:flex-start;gap:4px;}
    .tools-link{font-size:12px;}
    .music-page :global(button:not(.icon-button)),.music-page :global(select){min-height:44px;}
    .music-page :global(.widget){min-width:0;}
  }
</style>
