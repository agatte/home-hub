<script>
  // #157: Music's opt-in visual archetype, never a playback or preference writer.
  // All existing music interactions stay on the functional /music route.
  import { withQuietAtlasShell } from '$lib/quietAtlas/navigation.js'

  const musicTools = withQuietAtlasShell('/music')
  const approvedTrack = withQuietAtlasShell('/music#approved-apple-track')
</script>

<svelte:head>
  <title>Music · Quiet Atlas design review | HomeHub</title>
  <meta name="description" content="A read-only Quiet Atlas listening directory. Existing discovery, Sonos and Apple Music controls stay on the functional Music page." />
</svelte:head>

<main class="music-review" aria-label="Quiet Atlas Music design review">
  <div class="masthead">
    <span>QUIET ATLAS <span aria-hidden="true">×</span> MUSIC</span>
    <span class="review-status">READ-ONLY DESIGN REVIEW</span>
  </div>

  <header class="hero">
    <div class="hero-copy">
      <p class="eyebrow">THE LISTENING ROOM / 01</p>
      <h1>Music for the <em>moment you're in.</em></h1>
      <p class="summary">A calmer path to discovery, deliberate listening and the tools that shape your library. The actual music controls remain exactly where they are while this experience takes shape.</p>
      <a class="primary-link" href={musicTools}>
        <span>Open current Music tools</span>
        <span aria-hidden="true">↗</span>
      </a>
      <p class="action-note">Existing tools are functional and may change preferences, approval, Sonos or playback. This design page does none of those things.</p>
    </div>
    <div class="composition">
      <div class="disc" aria-hidden="true">
        <div class="disc-core"></div>
      </div>
      <div class="composition-caption">
        <span>THE QUIET BETWEEN SONGS</span>
        <small>Abstract design study · no live track or speaker state</small>
      </div>
    </div>
  </header>

  <section class="destinations" aria-labelledby="music-journeys-title">
    <div class="section-title">
      <span class="eyebrow">02 / WHERE TO GO</span>
      <h2 id="music-journeys-title">One place to find <em>your next listen.</em></h2>
      <p>Three distinct jobs, one existing functional destination. Nothing is started merely by opening this review.</p>
      <a class="artist-preview-link" href="/quiet-atlas/music/artist-review">Preview fictional artist matching <span aria-hidden="true">↗</span></a>
      <p class="artist-preview-note">Session-only fictional review. No Apple history or catalog requests.</p>
    </div>
    <nav class="journeys" aria-label="Current music destinations">
      <a class="journey" href={musicTools} aria-label="Open existing Music discovery and suggestions">
        <span class="journey-index">01 <span aria-hidden="true">/</span> DISCOVER</span>
        <span class="journey-main">
          <strong>Find what fits.</strong>
          <small>Explore contextual discovery previews and reviewed suggestions in the existing Music experience.</small>
        </span>
        <span class="journey-action" aria-hidden="true">↗</span>
      </a>
      <a class="journey" href={approvedTrack} aria-label="Open existing approved Apple Music track playback tools">
        <span class="journey-index">02 <span aria-hidden="true">/</span> LISTEN</span>
        <span class="journey-main">
          <strong>Choose a track deliberately.</strong>
          <small>Go to the existing exact-track approval and playback section. Its separate checks and confirmations still apply.</small>
        </span>
        <span class="journey-action" aria-hidden="true">↗</span>
      </a>
      <a class="journey" href={musicTools} aria-label="Open existing Music management and diagnostics">
        <span class="journey-index">03 <span aria-hidden="true">/</span> MANAGE</span>
        <span class="journey-main">
          <strong>Keep the details close.</strong>
          <small>Expand Manage music on the existing page for taste, mappings and advanced diagnostic tools.</small>
        </span>
        <span class="journey-action" aria-hidden="true">↗</span>
      </a>
    </nav>
  </section>

  <footer class="endnote">
    <p>Navigation-only preview. No catalog, personal taste, source availability, music selection, speaker status or playback is read, inferred or changed here.</p>
    <a href="/quiet-atlas/home">Return to Home <span aria-hidden="true">↗</span></a>
  </footer>
</main>

<style>
  .music-review { --ink:#e9eee6; --muted:#b0c0b0; --gold:#e0c89b; --line:rgba(200,222,199,.18); background:radial-gradient(ellipse at 80% 7%,rgba(134,151,107,.12),transparent 46%),#101b15; color:var(--ink); min-height:100%; padding:clamp(18px,3vw,42px) clamp(17px,4vw,56px) 54px; font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
  .music-review * { box-sizing:border-box; }
  .music-review a { color:inherit; text-decoration:none; }
  .music-review a:focus-visible { outline:3px solid #d5e7bd; outline-offset:4px; }
  .masthead { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:9px 20px; padding-bottom:19px; border-bottom:1px solid var(--line); color:var(--gold); font-size:10px; font-weight:700; letter-spacing:.15em; }
  .masthead span span { padding:0 5px; color:#a2b2a0; }
  .review-status { color:var(--muted); font-size:9px; }
  .hero { display:grid; grid-template-columns:minmax(0,1.05fr) minmax(260px,.95fr); gap:clamp(25px,4vw,70px); padding:clamp(46px,7vw,92px) 0 clamp(34px,5vw,70px); align-items:center; border-bottom:1px solid var(--line); }
  .eyebrow { margin:0; color:var(--gold); font-size:10px; font-weight:750; letter-spacing:.16em; }
  h1 { font:550 clamp(41px,5.5vw,80px)/1.04 system-ui,-apple-system,"Segoe UI",sans-serif; letter-spacing:-.06em; max-width:790px; margin:22px 0 25px; }
  h1 em,h2 em { font-family:Georgia,"Times New Roman",serif; font-weight:400; letter-spacing:-.045em; }
  .summary { max-width:535px; color:var(--muted); font-size:14px; line-height:1.82; margin:0 0 28px; }
  .primary-link { display:inline-flex; align-items:center; justify-content:space-between; gap:30px; min-height:50px; padding:11px 19px; border-radius:3px; background:#e2d1ac; color:#19271d !important; font-size:13px; font-weight:750; }
  .primary-link:hover { background:#f0dfbc; }
  .action-note { max-width:465px; color:#9fb19f; font-size:11px; line-height:1.7; margin:14px 0 0; }
  .composition { min-height:360px; display:flex; flex-direction:column; align-items:center; justify-content:center; position:relative; overflow:hidden; isolation:isolate; background:radial-gradient(ellipse at 45% 42%,rgba(207,180,130,.13),transparent 55%),radial-gradient(ellipse at 65% 80%,rgba(71,116,100,.15),transparent 57%),linear-gradient(150deg,#1a2a20,#0c1512); border:1px solid rgba(200,222,199,.13); }
  .composition:before,.composition:after { content:""; position:absolute; inset:20px; border:1px solid rgba(200,222,199,.07); pointer-events:none; }
  .composition:after { inset:35px; border-color:rgba(200,222,199,.035); }
  .disc { width:min(54%,270px); aspect-ratio:1; border-radius:50%; display:grid; place-items:center; background:repeating-radial-gradient(circle,rgba(234,213,172,.17) 0 1px,transparent 2px 8px),radial-gradient(circle at 42% 34%,#5b664d 0%,#2d4134 37%,#121f1a 75%); border:1px solid rgba(225,206,167,.55); box-shadow:0 16px 55px rgba(3,8,5,.55),inset 0 0 42px rgba(0,0,0,.3); }
  .disc-core { width:27%; aspect-ratio:1; border-radius:50%; display:grid; place-items:center; border:1px solid rgba(233,214,173,.45); background:radial-gradient(circle,#e0c89b 0 9%,#586d56 13%,#263d30 55%); }
  .composition-caption { position:relative; z-index:1; text-align:center; margin-top:35px; padding:0 18px 9px; display:flex; flex-direction:column; gap:7px; }
  .composition-caption span { color:#d7c398; font-size:10px; font-weight:700; letter-spacing:.16em; }
  .composition-caption small { color:#acc0ae; font-size:10px; line-height:1.4; }
  .destinations { display:grid; grid-template-columns:minmax(190px,.67fr) minmax(0,1.33fr); gap:clamp(25px,5vw,75px); padding:clamp(32px,5vw,60px) 0; border-bottom:1px solid var(--line); }
  h2 { font:400 clamp(26px,2.9vw,42px)/1.18 Georgia,"Times New Roman",serif; letter-spacing:-.04em; margin:19px 0 16px; }
  .section-title p { max-width:290px; color:var(--muted); font-size:12px; line-height:1.8; margin:0; }
  .journeys { min-width:0; }
  .journey { display:grid; grid-template-columns:minmax(80px,.32fr) minmax(0,1fr) 28px; gap:clamp(12px,2.4vw,26px); align-items:center; border-bottom:1px solid var(--line); min-height:120px; padding:17px 0; }
  .journey:first-child { border-top:1px solid var(--line); }
  .journey:hover { border-color:rgba(224,200,155,.65); }
  .journey-index { align-self:start; color:var(--gold); font-size:10px; font-weight:750; letter-spacing:.12em; line-height:1.5; padding-top:5px; }
  .journey-index span { color:#768e7b; padding:0 5px; }
  .journey-main { display:flex; flex-direction:column; min-width:0; gap:8px; }
  .journey-main strong { font:400 clamp(21px,2.2vw,29px)/1.25 Georgia,"Times New Roman",serif; letter-spacing:-.025em; }
  .journey-main small { color:var(--muted); font-size:12px; line-height:1.65; }
  .journey-action { color:var(--gold); font-size:22px; justify-self:end; }
  .artist-preview-link { display:inline-flex; align-items:center; justify-content:space-between; gap:16px; min-height:48px; padding:9px 13px; margin-top:21px; text-decoration:none; color:#19271d !important; background:#e2d1ac; font-size:12px; font-weight:700; }
  .artist-preview-link:hover { background:#f0dfbc; }
  .artist-preview-note { margin:9px 0 0 !important; color:var(--muted); font-size:11px !important; }
  .endnote { display:flex; align-items:start; justify-content:space-between; gap:26px; padding-top:25px; font-size:11px; line-height:1.75; color:var(--muted); }
  .endnote p { max-width:750px; margin:0; }
  .endnote a { display:inline-flex; align-items:center; gap:11px; min-height:44px; flex:0 0 auto; font-weight:650; color:var(--ink); }
  @media(max-width:920px) { .hero { grid-template-columns:minmax(0,1fr); } .composition { min-height:290px; } .disc { width:min(36%,210px); } .destinations { grid-template-columns:minmax(0,1fr); gap:25px; } .section-title p { max-width:620px; } }
  @media(max-width:600px) { .music-review { padding:18px 17px 38px; } .masthead { font-size:9px; } .review-status { font-size:8px; } .hero { padding:38px 0 31px; gap:29px; } h1 { font-size:clamp(37px,10vw,52px); margin:17px 0 19px; } .summary { font-size:12px; line-height:1.7; margin-bottom:22px; } .primary-link { width:100%; min-height:48px; } .composition { min-height:226px; } .disc { width:130px; } .composition-caption { margin-top:14px; } .destinations { padding:30px 0; } h2 { font-size:30px; margin:12px 0; } .journey { grid-template-columns:minmax(0,1fr) 22px; gap:11px; min-height:0; padding:22px 0; } .journey-index { grid-column:1/-1; padding:0; } .journey-main strong { font-size:23px; } .journey-main small { font-size:11px; } .endnote { flex-direction:column; gap:13px; } }
  @media(prefers-reduced-motion:reduce) { .music-review a { scroll-behavior:auto; } }
</style>
