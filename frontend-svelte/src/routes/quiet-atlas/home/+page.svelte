<script>
  // #270: isolated visual review. No HomeHub stores, API reads, or device actions.
  let daylight = false
  let sampleState = 'unavailable'

  const groups = [
    { name: 'Living', detail: 'L1', label: 'Browse Living lights' },
    { name: 'Bedroom', detail: 'L2 · L5', label: 'Browse Bedroom lights' },
    { name: 'Kitchen', detail: 'L3 · L4', label: 'Browse Kitchen lights' },
    { name: 'Plant', detail: 'L6', label: 'Browse Plant lighting' },
  ]

  const examples = {
    unavailable: {
      title: 'No live context connected',
      description: 'House State and Activity have not been read by this design study.',
      kind: 'Unavailable',
    },
    stale: {
      title: 'Lighting reading unverified',
      description: 'A stale light reading cannot establish current bulb state or change House State.',
      kind: 'Stale example',
    },
    empty: {
      title: 'Nothing to report yet',
      description: 'A quiet, empty event rail should leave space for the apartment.',
      kind: 'Empty example',
    },
    attention: {
      title: 'Manual lighting ownership',
      description: 'An example reminder that manual controls take precedence over automatic suggestions.',
      kind: 'Attention example',
    },
  }

  $: example = examples[sampleState] ?? examples.unavailable
</script>

<svelte:head>
  <title>Home · Quiet Atlas design review | HomeHub</title>
  <meta name="description" content="Isolated, read-only HomeHub Quiet Atlas × Daylight Home composition preview." />
</svelte:head>

<main class:daylight class="home-review" aria-label="Quiet Atlas Home design review">
  <div class="preview-ribbon">
    <span class="brand">QUIET ATLAS <span class="multiply">×</span> DAYLIGHT</span>
    <span class="disclaimer">Illustrative design preview · not live HomeHub state</span>
    <button
      class="theme-toggle"
      type="button"
      on:click={() => (daylight = !daylight)}
      aria-label={daylight ? 'Use night preview' : 'Use day preview'}
      aria-pressed={daylight}
    >{daylight ? 'Night view' : 'Day view'}</button>
  </div>

  <header class="foreword">
    <div>
      <p class="eyebrow">HOME / OVERVIEW</p>
      <h1>The apartment, <em>at ease.</em></h1>
      <p class="subhead">A quieter way to understand home, then change what matters.</p>
    </div>
    <a class="apartment-link" href="/" aria-label="Open existing Apartment and household tools">
      <span class="icon-dot" aria-hidden="true"></span>
      Apartment & household tools <span aria-hidden="true">↗</span>
    </a>
  </header>

  <section class="apartment-stage" aria-labelledby="apartment-stage-title">
    <div class="world">
      <div class="ambient-orb" aria-hidden="true"></div>
      <div class="world-topline">
        <span>01 / THE APARTMENT</span>
        <span class="source">SPATIAL PLACEHOLDER · NOT A FLOOR PLAN</span>
      </div>
      <div class="world-message">
        <p class="world-kicker">YOUR SPACE</p>
        <h2 id="apartment-stage-title">A home that feels present, <em>without the noise.</em></h2>
        <p>Actual apartment geometry and its cinematic view will come from the separate, evidence-checked Apartment Canvas (#192).</p>
      </div>
      <div class="world-bottom">
        <div class="readout">
          <span>HOUSE STATE</span>
          <strong>Not connected</strong>
        </div>
        <div class="readout">
          <span>ACTIVITY</span>
          <strong>Not connected</strong>
        </div>
        <div class="world-note">No presence, room or lighting state is inferred by this preview.</div>
      </div>
    </div>
    <aside class="context-rail" aria-label="Recent context example">
      <p class="rail-head">RECENT CONTEXT <span aria-hidden="true">—</span></p>
      <p class="rail-title">{example.title}</p>
      <p class="rail-description">{example.description}</p>
      <p class="rail-kind">{example.kind}</p>
      <label class="sample-label" for="sample-state">Review an example state</label>
      <select id="sample-state" bind:value={sampleState}>
        <option value="unavailable">Unavailable</option>
        <option value="stale">Stale light reading</option>
        <option value="empty">Empty history</option>
        <option value="attention">Manual ownership</option>
      </select>
      <a class="rail-footer" href="/analytics?shell=quiet-atlas">View Insights <span aria-hidden="true">↗</span></a>
    </aside>
  </section>

  <section class="lighting-dock" aria-labelledby="lighting-title">
    <div class="dock-head">
      <div>
        <p class="eyebrow">THE EVERYDAY CONTROLS</p>
        <h2 id="lighting-title">Lighting, within reach.</h2>
      </div>
      <a class="browse-link" href="/quiet-atlas">Open lighting review <span aria-hidden="true">↗</span></a>
    </div>
    <div class="groups" aria-label="Browse lighting groups">
      {#each groups as group}
        <a href="/quiet-atlas" class="group" aria-label={group.label}>
          <span class="group-mark" aria-hidden="true"></span>
          <span class="group-copy"><strong>{group.name}</strong><small>{group.detail} · view lights</small></span>
          <span class="group-arrow" aria-hidden="true">↗</span>
        </a>
      {/each}
    </div>
    <div class="scene-line">
      <span><strong>Scenes & presets</strong><small>Browse names from the existing read-only lighting review; no sample scenes are activated.</small></span>
      <a href="/quiet-atlas">Browse scenes <span aria-hidden="true">↗</span></a>
    </div>
  </section>

  <section class="mobile-context" aria-label="Recent context example">
    <span class="mobile-context-kind">{example.kind}</span>
    <p><strong>{example.title}</strong> — {example.description}</p>
    <label for="mobile-review-state">Review example state</label>
    <select id="mobile-review-state" bind:value={sampleState}>
      <option value="unavailable">Unavailable</option>
      <option value="stale">Stale light reading</option>
      <option value="empty">Empty history</option>
      <option value="attention">Manual ownership</option>
    </select>
    <a href="/analytics?shell=quiet-atlas">Open Insights ↗</a>
  </section>

  <footer class="review-footer">
    <span>This route never sends lighting or scene commands.</span>
    <a href="/quiet-atlas">Back to lighting preview</a>
  </footer>
</main>

<style>
  .home-review {
    --bg: #101a15;
    --stage: #1a2a21;
    --deep: #0f211b;
    --line: rgba(224,235,214,.14);
    --ink: #f7f3e8;
    --muted: #b4c6b5;
    --gold: #edcfa0;
    --glow: rgba(155,179,117,.24);
    color: var(--ink);
    background: radial-gradient(ellipse at 72% 12%,rgba(178,154,104,.09),transparent 50%),var(--bg);
    padding: 28px clamp(19px,4vw,64px) 26px;
    min-height: 100%;
    font-family: system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  .home-review.daylight {
    --bg:#eeeee6; --stage:#e0e5d8; --deep:#d5dfd3; --line:rgba(45,77,55,.18);
    --ink:#263a2d; --muted:#5b6d5f; --gold:#805f37; --glow:rgba(177,152,112,.14);
  }
  button,select { font:inherit; }
  button, a, select { -webkit-tap-highlight-color:transparent; }
  a { color:inherit;text-decoration:none; }
  a:focus-visible,button:focus-visible,select:focus-visible { outline:3px solid var(--gold);outline-offset:3px; }
  .preview-ribbon { display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-height:28px;color:var(--muted);font-size:11px; }
  .brand {font-size:10px;font-weight:800;letter-spacing:.13em;color:var(--gold);}
  .multiply {color:var(--muted);margin:0 5px;}
  .disclaimer {flex:1;min-width:190px;}
  .theme-toggle {background:transparent;border:1px solid var(--line);border-radius:99px;color:var(--ink);padding:7px 14px;cursor:pointer;}
  .foreword {display:flex;align-items:end;justify-content:space-between;gap:16px;margin:24px 0 23px;}
  .eyebrow,.world-kicker {font-size:10px;letter-spacing:.14em;font-weight:750;color:var(--gold);margin:0 0 9px;}
  h1,h2,p {margin-top:0;}
  h1 {font-size:clamp(29px,3.2vw,43px);font-weight:610;letter-spacing:-.045em;line-height:1.13;margin-bottom:7px;}
  h1 em,.world-message h2 em {font-weight:400;font-family:Georgia,serif;letter-spacing:-.025em;}
  .subhead {font-size:13px;color:var(--muted);margin:0;}
  .apartment-link {display:inline-flex;align-items:center;gap:10px;border:1px solid var(--line);padding:12px 16px;border-radius:100px;font-size:12px;white-space:nowrap;min-height:44px;}
  .icon-dot {width:8px;height:8px;border:1px solid var(--gold);transform:rotate(45deg);}
  .apartment-stage {display:grid;grid-template-columns:minmax(0,1fr) minmax(235px,280px);border:1px solid var(--line);border-radius:19px;overflow:hidden;min-height:380px;}
  .world {position:relative;min-width:0;overflow:hidden;background:radial-gradient(ellipse at 47% 45%,var(--glow),transparent 53%),linear-gradient(130deg,var(--stage),var(--deep));padding:22px 27px;display:flex;flex-direction:column;justify-content:space-between;isolation:isolate;}
  .ambient-orb {position:absolute;width:390px;height:390px;right:4%;top:-19%;z-index:-1;border-radius:50%;background:radial-gradient(circle at 45% 46%,rgba(237,207,160,.15),rgba(98,151,115,.07) 42%,transparent 69%);filter:blur(8px);pointer-events:none;}
  .world-topline {display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--muted);font-size:10px;letter-spacing:.1em;}
  .world-topline .source {font-size:9px;text-align:right;}
  .world-message {max-width:540px;margin:30px 0;}
  .world-message h2 {font-size:clamp(26px,3.2vw,43px);line-height:1.13;font-weight:570;letter-spacing:-.04em;margin:0 0 13px;}
  .world-message>p:last-child {color:var(--muted);font-size:13px;line-height:1.6;max-width:430px;margin:0;}
  .world-bottom {display:flex;align-items:end;gap:21px;flex-wrap:wrap;}
  .readout {display:flex;flex-direction:column;gap:7px;min-width:124px;}
  .readout span {font-size:10px;letter-spacing:.13em;color:var(--muted);}
  .readout strong {font-size:15px;font-weight:600;}
  .world-note {font-size:10px;color:var(--muted);margin-left:auto;max-width:170px;line-height:1.4;}
  .context-rail {border-left:1px solid var(--line);background:color-mix(in srgb,var(--stage) 80%,var(--bg));padding:25px 22px 20px;display:flex;flex-direction:column;}
  .rail-head {font-size:10px;letter-spacing:.14em;color:var(--gold);font-weight:750;display:flex;justify-content:space-between;}
  .rail-title {font-size:20px;font-weight:600;letter-spacing:-.025em;line-height:1.2;margin:45px 0 10px;}
  .rail-description {font-size:12px;line-height:1.55;color:var(--muted);}
  .rail-kind {font-size:11px;color:var(--gold);margin-bottom:24px;}
  .sample-label {font-size:10px;color:var(--muted);margin-top:auto;margin-bottom:8px;}
  .context-rail select {padding:9px;background:var(--deep);border:1px solid var(--line);border-radius:7px;color:var(--ink);width:100%;min-height:38px;}
  .rail-footer {display:flex;justify-content:space-between;border-top:1px solid var(--line);padding-top:14px;margin-top:18px;font-size:12px;}
  .lighting-dock {margin-top:25px;}
  .dock-head {display:flex;align-items:end;justify-content:space-between;gap:14px;margin-bottom:14px;}
  .dock-head h2 {font-size:23px;letter-spacing:-.035em;margin:0;font-weight:600;}
  .browse-link {font-size:12px;color:var(--gold);padding:9px 0;}
  .groups {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}
  .group {display:flex;align-items:center;gap:10px;min-width:0;min-height:76px;background:linear-gradient(145deg,var(--stage),var(--deep));border:1px solid var(--line);border-radius:11px;padding:12px 13px;}
  .group:hover,.apartment-link:hover {border-color:var(--gold);}
  .group-mark {width:10px;height:10px;border:2px solid var(--gold);border-radius:50%;flex:0 0 auto;opacity:.85;}
  .group-copy {display:flex;flex-direction:column;min-width:0;gap:4px;}
  .group-copy strong {font-size:14px;font-weight:600;white-space:nowrap;}
  .group-copy small {font-size:10px;color:var(--muted);white-space:nowrap;}
  .group-arrow {margin-left:auto;color:var(--muted);font-size:12px;}
  .scene-line {display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 2px;border-bottom:1px solid var(--line);}
  .scene-line>span {display:flex;flex-direction:column;gap:5px;}
  .scene-line strong {font-size:13px;}
  .scene-line small {font-size:11px;color:var(--muted);line-height:1.4;}
  .scene-line a {color:var(--gold);white-space:nowrap;font-size:12px;padding:10px 0;}
  .mobile-context {display:none;}
  .review-footer {display:flex;gap:10px;justify-content:space-between;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-top:23px;}
  .review-footer a {text-decoration:underline;}
  @media (max-width:960px) {
    .apartment-stage {grid-template-columns:minmax(0,1fr) 210px;}
    .world-note {display:none;}
    .group {padding:10px;gap:7px;}
    .group-copy small {font-size:9px;}
  }
  @media (max-width:700px) {
    .home-review {padding:14px 13px 16px;}
    .preview-ribbon {gap:8px;font-size:10px;}
    .brand {font-size:9px;}
    .disclaimer {flex-basis:calc(100% - 105px);min-width:0;line-height:1.25;}
    .theme-toggle {padding:5px 9px;font-size:10px;}
    .foreword {display:block;margin:14px 0 13px;}
    .eyebrow {font-size:9px;margin-bottom:6px;}
    h1 {font-size:29px;margin-bottom:4px;}
    .subhead {font-size:11px;}
    .apartment-link {display:none;}
    .apartment-stage {display:block;min-height:0;border-radius:14px;}
    .world {min-height:237px;padding:13px 15px 15px;}
    .world-topline {font-size:9px;}
    .world-topline .source {font-size:8px;max-width:136px;}
    .ambient-orb {width:250px;height:250px;top:-10%;}
    .world-message {margin:18px 0 17px;}
    .world-message h2 {font-size:25px;max-width:340px;margin-bottom:8px;}
    .world-message>p:last-child {font-size:10px;line-height:1.45;max-width:310px;}
    .world-bottom {gap:18px;}
    .readout {min-width:0;flex:1;gap:4px;}
    .readout span {font-size:8px;}
    .readout strong {font-size:12px;}
    .context-rail {display:none;}
    .lighting-dock {margin-top:14px;}
    .dock-head {margin-bottom:9px;}
    .dock-head h2 {font-size:20px;}
    .browse-link {font-size:10px;}
    .groups {grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
    .group {min-height:56px;border-radius:9px;padding:8px 10px;gap:9px;}
    .group-copy strong {font-size:13px;}
    .group-copy small {font-size:9px;}
    .scene-line {padding:10px 2px;}
    .scene-line strong {font-size:12px;}
    .scene-line small {font-size:9px;max-width:250px;}
    .scene-line a {font-size:10px;}
    .mobile-context {display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:13px;border-top:1px solid var(--line);padding-top:11px;font-size:10px;color:var(--muted);}
    .mobile-context-kind {font-size:9px;color:var(--gold);letter-spacing:.07em;text-transform:uppercase;}
    .mobile-context p {flex-basis:100%;line-height:1.45;margin:0;}
    .mobile-context strong {color:var(--ink);}
    .mobile-context label {font-size:9px;}
    .mobile-context select {min-height:34px;max-width:145px;min-width:0;flex:1;border:1px solid var(--line);border-radius:6px;color:var(--ink);background:var(--stage);padding:5px;}
    .mobile-context a {margin-left:auto;color:var(--gold);}
    .review-footer {font-size:9px;margin-top:14px;}
  }
  @media (max-width:360px) {
    .world-message h2 {font-size:22px;}
    .world {min-height:218px;}
    .browse-link {max-width:90px;text-align:right;}
    .group-arrow {display:none;}
    .scene-line small {max-width:165px;}
  }
  @media (prefers-reduced-motion:reduce) {
    .home-review * {transition:none!important;animation:none!important;}
  }
</style>
