<script>
  // #431: isolated fictional identity-review study. No catalog, import,
  // persisted preference, playback, HomeHub API, or third-party operation.
  const artists = [
    { name: 'Imaginary Atlas Ensemble', days: '10+ example days' },
    { name: 'Fictional Pattern Unit', days: '4–9 example days' },
    { name: 'Invented Sound Group', days: '2–3 example days' },
    { name: 'Makebelieve Echo Collective', days: '1 example day' },
  ]
  const candidates = [
    { name: 'Imaginary Atlas Ensemble', note: 'Invented lunar chamber ensemble' },
    { name: 'Fictional Pattern Unit', note: 'Invented geometric percussion group' },
    { name: 'Invented Sound Group', note: 'Invented paper instrument quartet' },
    { name: 'Invented Sound Group', note: 'Invented cloud instrument duo — distinct candidate' },
    { name: 'Makebelieve Echo Collective', note: 'Invented silent theatre ensemble' },
  ]
  const fixtures = [[0], [1], [2, 3], [4]]

  /** @typedef {'none' | 'accepted' | 'unsure'} DemoDecision */
  /** @typedef {{results: number[], chosen: number | null, decision: DemoDecision}} DemoRow */
  /** @returns {DemoRow[]} */
  const fresh = () => artists.map(() => ({ results: [], chosen: null, decision: 'none' }))
  /** @type {DemoRow[]} */
  let rows = fresh()
  let index = 0
  /** @type {'intro' | 'consent' | 'results' | 'done'} */
  let step = 'intro'
  /** @type {number | null} */
  let pending = null
  let announcement = 'Choose Find matches to begin.'

  $: artist = artists[index]
  $: row = rows[index]
  $: count = rows.filter((r) => r.decision === 'accepted').length

  /** @param {Partial<DemoRow>} patch */
  function updateRow(patch) {
    rows = rows.map((entry, n) => n === index ? { ...entry, ...patch } : entry)
  }

  /** @param {number} target */
  function navigate(target) {
    if (!Number.isInteger(target) || target < 0 || target >= artists.length) return
    // Switching artists revokes any uncommitted preview, but retains past choices.
    pending = null
    index = target
    const prior = rows[target]
    step = prior.decision === 'accepted' || prior.decision === 'unsure'
      ? 'done'
      : prior.results.length ? 'results' : 'intro'
    announcement = 'Now reviewing ' + artists[index].name + '.'
  }

  function next() {
    navigate((index + 1) % artists.length)
  }

  function preview() {
    if (!['intro', 'results', 'done'].includes(step)) return
    pending = index
    step = 'consent'
    announcement = 'Previewing this one fictional catalog request.'
  }

  function cancelPreview() {
    if (step !== 'consent') return
    pending = null
    step = rows[index].results.length ? 'results' : 'intro'
    announcement = 'Request preview canceled. Nothing transmitted.'
  }

  function revealResults() {
    // Only the artist whose per-query disclosure is on screen may be simulated.
    if (step !== 'consent' || pending !== index) return
    updateRow({ results: [...fixtures[index]], chosen: null, decision: 'none' })
    pending = null
    step = 'results'
    announcement = 'Fixed, fictional results ready. No network request was sent.'
  }

  /** @param {number} id */
  function chooseCandidate(id) {
    if (step !== 'results' || !rows[index].results.includes(id)) return
    updateRow({ chosen: id, decision: 'none' })
    announcement = 'Fictional candidate selected; not confirmed.'
  }

  function confirm() {
    if (step !== 'results' || rows[index].chosen === null) return
    updateRow({ decision: 'accepted' })
    step = 'done'
    announcement = 'Mock match confirmed for this session only.'
  }

  function unsure() {
    if (step !== 'results') return
    updateRow({ chosen: null, decision: 'unsure' })
    step = 'done'
    announcement = 'Artist left unresolved. No match was inferred.'
  }

  function undo() {
    if (step !== 'done' || rows[index].decision !== 'accepted') return
    updateRow({ decision: 'none' })
    step = 'results'
    announcement = 'Fictional match undone.'
  }

  function restart() {
    pending = null
    rows = fresh()
    index = 0
    step = 'intro'
    announcement = 'This fictional session was reset. All selections discarded.'
  }

  /** @param {KeyboardEvent} event */
  function keyboard(event) {
    if (event.key === 'Escape' && step === 'consent') {
      event.preventDefault()
      cancelPreview()
    }
  }
</script>

<svelte:head>
  <title>Match your artists · Quiet Atlas fictional review | HomeHub</title>
  <meta name="description" content="Fictional artist matching without catalog requests or saved review choices." />
</svelte:head>

<svelte:window on:keydown={keyboard} />

<main class="artist-review" aria-label="Fictional artist identity design review">
  <div class="masthead">
    <span>HOMEHUB / QUIET ATLAS <span aria-hidden="true">×</span> MUSIC</span>
    <span class="demo-status">FICTIONAL · NO CATALOG REQUESTS</span>
  </div>

  <header class="hero">
    <p class="eyebrow">ARTIST IDENTITY / REVIEW</p>
    <h1>Match your <em>artists.</em></h1>
    <p class="intro">One artist at a time. Find the right name, confirm it, or move on.</p>
  </header>

  <section class="review-stage" aria-label="Artist matching steps">
    <div class="work">
      <p class="eyebrow">{String(index + 1).padStart(2, '0')} / {String(artists.length).padStart(2, '0')} · ARTIST REVIEW</p>
      <h2>{artist.name}</h2>
      <p class="exposure">Appears on {artist.days}. This does not tell HomeHub whether you like this artist.</p>
      <div class="step">
        {#if step === 'intro'}
          <h3>Find the right artist.</h3>
          <p>See a few fictional catalog matches, then decide whether any look right.</p>
          <button type="button" class="primary" on:click={preview}>Find matches</button>
          <p class="fine-print">A future real lookup would ask permission before sending each artist name.</p>
        {:else if step === 'consent'}
          <h3>One artist. One permission.</h3>
          <div class="disclosure">
            <p><strong>Artist name:</strong> {artist.name}</p>
            <p><strong>Example recipient:</strong> DemoCatalog (fictional)</p>
            <p>In a future real lookup, that provider could observe your IP address and retain the query. It would not receive your Apple export, listening dates, or account data.</p>
          </div>
          <p class="fine-print">This review never contacts a catalog. Normal HomeHub shell connections are separate.</p>
          <button type="button" class="primary" on:click={revealResults}>Show fictional matches</button>
          <button type="button" class="quiet" on:click={cancelPreview}>Cancel this search</button>
        {:else if step === 'results'}
          <h3>Which one is the right match?</h3>
          <p>These candidates are made up. Identical artist names do not prove identical identities.</p>
          <fieldset class="options">
            <legend>Choose one fictional candidate</legend>
            {#each row.results as candidateIndex (candidateIndex)}
              <label class:chosen={row.chosen === candidateIndex}>
                <input
                  type="radio"
                  name="fictional-candidate"
                  value={candidateIndex}
                  checked={row.chosen === candidateIndex}
                  on:change={() => chooseCandidate(candidateIndex)}
                />
                <span><strong>{candidates[candidateIndex].name}</strong><small>{candidates[candidateIndex].note}</small></span>
              </label>
            {/each}
          </fieldset>
          <button type="button" class="primary" disabled={row.chosen === null} on:click={confirm}>Confirm fictional match</button>
          <button type="button" class="quiet" on:click={unsure}>None look right / I'm not sure</button>
          <button type="button" class="quiet" on:click={preview}>Search again (fictional)</button>
        {:else if step === 'done'}
          {#if row.decision === 'accepted'}
            <h3>A match, for this session.</h3>
            <p>Selected: <strong>{row.chosen === null ? 'Unverified' : candidates[row.chosen].name}</strong>. This is an invented identity choice, not a preference rating or real catalog verification.</p>
            <button type="button" class="primary" on:click={next}>Continue to next artist</button>
            <button type="button" class="quiet" on:click={undo}>Undo this match</button>
          {:else}
            <h3>Nothing selected.</h3>
            <p>That's okay. It's better to leave an identity unresolved than to guess.</p>
            <button type="button" class="primary" on:click={next}>Continue to next artist</button>
            <button type="button" class="quiet" on:click={preview}>Try this artist again</button>
          {/if}
        {/if}
      </div>
    </div>

    <aside class="context" aria-label="Listening Room visual and privacy information">
      <p class="eyebrow">THE LISTENING ROOM</p>
      <img src="/design-review/artist-light-waves-431.png" width="178" height="178" alt="" aria-hidden="true" />
      <p class="tally">{count} of {artists.length} matched in this fictional session</p>
      <div class="context-rule"></div>
      <p class="eyebrow">NO CATALOG REQUEST SENT</p>
      <p>Made-up artists only. No real catalog connection. Nothing saved.</p>
    </aside>
  </section>

  <footer class="footer">
    <p class="status" aria-live="polite" aria-atomic="true">{announcement}</p>
    <div class="foot-nav">
      <div class="history">
        <button type="button" class="quiet" on:click={() => navigate(index - 1)} disabled={index === 0}>Previous artist</button>
        <button type="button" class="quiet" on:click={next}>{index === artists.length - 1 ? 'Return to first artist' : 'Next artist'}</button>
      </div>
      <div class="history">
        <button type="button" class="quiet" on:click={restart}>Start over</button>
        <a href="/quiet-atlas/music">Close / discard <span class="sr-only">the fictional review and return to Music</span></a>
      </div>
    </div>
    <p class="footnote">Fictional-only opt-in study. This review makes no Apple catalog requests, no HomeHub API calls, no saved preferences, and no playback or device changes.</p>
  </footer>
</main>

<style>
  /*
   * #431 Quiet Atlas Music: one content-container scale drives the reading
   * column, Listening Room art/rail and editorial typography together.
   * @container sizes are based on space *inside HomeHub's shell*, not the
   * external browser viewport. Mobile uses a single column with page scroll.
   */
  .artist-review {
    --ink: #e9eee6;
    --muted: #b0c0b0;
    --gold: #e0c89b;
    --line: rgba(200, 222, 199, .18);
    box-sizing: border-box;
    container-type: inline-size;
    width: 100%;
    max-width: 1160px;
    min-height: 100%;
    margin-inline: auto;
    padding: clamp(18px, 3vw, 36px) clamp(17px, 3vw, 36px) 36px;
    color: var(--ink);
    background: radial-gradient(ellipse at 78% 4%, rgba(134,151,107,.09), transparent 42%), #101b15;
    font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .artist-review * { box-sizing: border-box; }
  .masthead {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--line);
    color: var(--gold);
    font-size: 10px;
    font-weight: 750;
    letter-spacing: .11em;
  }
  .masthead .demo-status { color: var(--muted); font-size: 9px; }
  .hero { padding: clamp(26px, 4cqw, 44px) 0 24px; border-bottom: 1px solid var(--line); }
  .eyebrow { margin: 0; color: var(--gold); font-size: 10px; font-weight: 750; letter-spacing: .13em; }
  h1 {
    margin: 14px 0 9px;
    font-size: clamp(40px, calc(16px + 3.0769cqw), 48px);
    font-weight: 650;
    letter-spacing: -.05em;
    line-height: 1.1;
  }
  h1 em { color: var(--gold); font-family: Georgia, "Times New Roman", serif; font-weight: 400; }
  .intro { margin: 0; color: var(--muted); line-height: 1.65; }

  .review-stage {
    /* Calibrated to the accepted 900–1160px Coordinated Scale desktop study. */
    --rail-width: clamp(214px, calc(94px + 15.3846cqw), 254px);
    --art-width: clamp(178px, calc(58px + 15.3846cqw), 218px);
    --read-width: clamp(534px, calc(300px + 30cqw), 610px);
    --artist-font: clamp(28px, calc(10px + 2.3077cqw), 34px);
    --section-font: clamp(23px, calc(11px + 1.5385cqw), 27px);
    display: grid;
    grid-template-columns: minmax(0, 1fr) var(--rail-width);
    align-items: start;
    gap: clamp(24px, 2.6cqw, 32px);
    padding: 22px 0 23px;
    border-bottom: 1px solid var(--line);
  }
  .work { min-width: 0; }
  h2 {
    margin: 11px 0 6px;
    font: 400 var(--artist-font)/1.2 Georgia, "Times New Roman", serif;
    letter-spacing: -.035em;
    overflow-wrap: anywhere;
  }
  .exposure { max-width: var(--read-width); margin: 0 0 17px; color: var(--muted); font-size: 12px; line-height: 1.6; }
  .step {
    width: min(100%, calc(var(--read-width) + 20px));
    min-height: 205px;
    /* Short desktop windows keep the nav available; long steps alone scroll. */
    max-height: clamp(210px, calc(100dvh - 535px), 500px);
    overflow-y: auto;
    overscroll-behavior-y: contain;
    scrollbar-width: thin;
    scrollbar-gutter: stable;
    scrollbar-color: #637c66 transparent;
    padding: 17px 10px 4px 0;
    border-top: 1px solid var(--line);
  }
  h3 { margin: 0 0 9px; font: 400 var(--section-font)/1.22 Georgia, "Times New Roman", serif; }
  .step > p { max-width: var(--read-width); margin: 0 0 15px; color: var(--muted); line-height: 1.65; }
  .primary {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 52px;
    width: 100%;
    max-width: var(--read-width);
    padding: 12px 16px;
    border: 1px solid transparent;
    background: #e2d1ac;
    color: #19271d;
    font-family: inherit;
    font-size: clamp(14px, calc(11px + .3846cqw), 15px);
    line-height: 1.35;
    font-weight: 700;
    text-align: center;
    cursor: pointer;
  }
  .primary:not(:disabled):hover { background: #f0dfbc; }
  .primary:disabled { opacity: .48; cursor: not-allowed; }
  .quiet {
    min-height: 44px;
    padding: 8px 7px;
    color: var(--ink);
    background: transparent;
    border: 1px solid transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .quiet:hover:not(:disabled) { color: var(--gold); }
  .quiet:disabled { opacity: .42; cursor: not-allowed; }
  .step > .quiet { display: block; margin-top: 7px; }
  .step .fine-print { color: #9fb19f; font-size: 12px; line-height: 1.65; margin-top: 15px; }
  .disclosure {
    width: 100%;
    border-left: 2px solid #c8b485;
    background: #18291f;
    padding: 12px 17px;
    margin-bottom: 14px;
  }
  .disclosure p { color: var(--muted); margin: 5px 0 8px; font-size: 12px; line-height: 1.6; }
  .disclosure p strong { color: var(--ink); }
  .options { min-width: 0; border: 0; padding: 0; margin: 0 0 14px; }
  .options legend { color: var(--muted); font-size: 12px; padding: 0 0 8px; }
  .options label {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 64px;
    padding: 11px;
    margin: 7px 0;
    border: 1px solid var(--line);
    background: rgba(62,91,71,.18);
    cursor: pointer;
  }
  .options label.chosen { border-color: #e0c89b; background: rgba(196,169,111,.12); }
  .options input {
    appearance: auto;
    flex: 0 0 20px;
    width: 20px;
    height: 20px;
    accent-color: #e2d1ac;
    cursor: pointer;
  }
  .options label span { min-width: 0; overflow-wrap: anywhere; }
  .options strong, .options small { display: block; }
  .options strong { font-size: 13px; font-weight: 650; }
  .options small { color: var(--muted); font-size: 11px; margin-top: 3px; line-height: 1.5; }

  .context {
    align-self: start;
    width: 100%;
    min-width: 0;
    padding: 14px;
    border: 1px solid var(--line);
    background: rgba(22,40,28,.62);
  }
  .context img {
    display: block;
    width: min(100%, var(--art-width));
    max-width: none;
    height: auto;
    aspect-ratio: 1;
    margin: 14px auto 12px;
    object-fit: contain;
  }
  .context .tally {
    margin: 0;
    color: var(--ink);
    font-size: clamp(12px, calc(9px + .3846cqw), 13px);
    font-weight: 650;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  .context-rule { margin: 13px 0 10px; height: 1px; background: var(--line); }
  .context p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; }

  .footer { padding-top: 12px; }
  .status { margin: 0 0 6px; color: var(--muted); min-height: 21px; font-size: 12px; }
  .foot-nav { display: flex; justify-content: space-between; gap: 14px; align-items: center; flex-wrap: wrap; }
  .history { display: flex; align-items: center; flex-wrap: wrap; gap: 11px; }
  .foot-nav a {
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    padding: 8px 7px;
    color: var(--ink);
    text-decoration: none;
  }
  .foot-nav a:hover { color: var(--gold); }
  button:focus-visible, a:focus-visible, input:focus-visible { outline: 3px solid #d5e7bd; outline-offset: 3px; }
  .footnote { margin: 12px 0 0; color: var(--muted); font-size: 10px; line-height: 1.5; }
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0,0,0,0);
    white-space: nowrap;
    border: 0;
  }

  /* Breakpoint follows available HomeHub page width, not outer window width. */
  @container (max-width: 800px) {
    .review-stage { grid-template-columns: minmax(0, 1fr); gap: 14px; padding-top: 19px; }
    .step { width: 100%; max-height: none; overflow: visible; scrollbar-gutter: auto; }
    .context {
      display: grid;
      grid-template-columns: minmax(0, 1fr) min(25cqw, 110px);
      align-items: start;
      column-gap: 14px;
    }
    .context .eyebrow { grid-column: 1; }
    .context img { grid-column: 2; grid-row: 1 / 5; width: 100%; margin: 0; }
    .context .tally { grid-column: 1; margin-top: 9px; }
    .context-rule { grid-column: 1; margin: 10px 0 5px; }
    .context p:last-child { grid-column: 1; margin: 5px 0 0; }
    h2 { font-size: clamp(27px, 4.3cqw, 31px); }
    h3 { font-size: clamp(22px, 3.7cqw, 26px); }
  }
  @container (max-width: 420px) {
    .context { grid-template-columns: minmax(0, 1fr) min(25cqw, 88px); column-gap: 10px; }
    .foot-nav { align-items: stretch; }
    .history { gap: 6px; }
    h1 { font-size: clamp(35px, 9cqw, 40px); }
  }
  @media (max-width: 700px) {
    .artist-review { padding-inline: 17px; }
  }
  @media (max-width: 360px) {
    .artist-review { padding-inline: 15px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .artist-review *, .artist-review *::before, .artist-review *::after {
      scroll-behavior: auto !important;
      animation: none !important;
      transition: none !important;
    }
  }
</style>
