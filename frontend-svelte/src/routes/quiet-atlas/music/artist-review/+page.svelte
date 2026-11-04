<script>
  import { tick } from 'svelte'
  import packet from '$lib/appleMusicArtistReviewHandoff431.fixture.json'
  import { adaptSyntheticArtistReview431 } from '$lib/appleMusicArtistReviewHandoff431.js'

  // Static repository fixture only. No route data, query, upload or private input.
  const { artists, candidates, fixtures } = adaptSyntheticArtistReview431(packet)

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
  /** @type {HTMLElement | null} */
  let stepHeading = null

  // A button disappears whenever an active step changes. Restore the
  // keyboard/screen-reader reading position after Svelte swaps the markup.
  async function focusStepHeading() {
    await tick()
    const heading = stepHeading
    if (!heading) return
    heading.focus({ preventScroll: true })
    // Focus must also remain visible after actions at the bottom of a long
    // phone screen. Only scroll when needed; don't jump on routine clicks.
    const bounds = heading.getBoundingClientRect()
    if ((bounds.top < 80 || bounds.bottom > window.innerHeight - 84) &&
        typeof heading.scrollIntoView === 'function') {
      heading.scrollIntoView({ block: 'center', behavior: 'auto' })
    }
  }

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
    void focusStepHeading()
  }

  function next() {
    navigate((index + 1) % artists.length)
  }

  function preview() {
    if (!['intro', 'results', 'done'].includes(step)) return
    pending = index
    step = 'consent'
    announcement = 'Previewing this one fictional catalog request.'
    void focusStepHeading()
  }

  function cancelPreview() {
    if (step !== 'consent') return
    pending = null
    step = rows[index].results.length ? 'results' : 'intro'
    announcement = 'Request preview canceled. Nothing transmitted.'
    void focusStepHeading()
  }

  function revealResults() {
    // Only the artist whose per-query disclosure is on screen may be simulated.
    if (step !== 'consent' || pending !== index) return
    updateRow({ results: [...fixtures[index]], chosen: null, decision: 'none' })
    pending = null
    step = 'results'
    announcement = 'Fixed, fictional results ready. No network request was sent.'
    void focusStepHeading()
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
    void focusStepHeading()
  }

  function unsure() {
    if (step !== 'results') return
    updateRow({ chosen: null, decision: 'unsure' })
    step = 'done'
    announcement = 'Artist left unresolved. No match was inferred.'
    void focusStepHeading()
  }

  function undo() {
    if (step !== 'done' || rows[index].decision !== 'accepted') return
    updateRow({ decision: 'none' })
    step = 'results'
    announcement = 'Fictional match undone.'
    void focusStepHeading()
  }

  function restart() {
    pending = null
    rows = fresh()
    index = 0
    step = 'intro'
    announcement = 'This fictional session was reset. All selections discarded.'
    void focusStepHeading()
  }

  /** @param {KeyboardEvent} event */
  function keyboard(event) {
    if (event.key !== 'Escape' || step !== 'consent') return
    // The shell's More dialog owns Escape while it is open. Inert background
    // content still receives a svelte:window key handler unless guarded.
    if (event.defaultPrevented || document.querySelector('[role="dialog"][aria-modal="true"]')) return
    event.preventDefault()
    cancelPreview()
  }
</script>

<svelte:head>
  <title>Artist review · Quiet Atlas fictional preview | HomeHub</title>
  <meta name="description" content="Fictional artist matching without catalog requests or saved review choices." />
</svelte:head>

<svelte:window on:keydown={keyboard} />

<main class="artist-review" aria-label="Fictional artist identity design review">
  <div class="review-container">
    <nav class="review-top" aria-label="Artist review navigation">
      <span class="review-ident">Artist review <span aria-hidden="true">·</span> {index + 1} of {artists.length}</span>
      <a class="close-link" href="/quiet-atlas/music">Close review</a>
    </nav>
     <header class="review-hero">
      <div class="hero-copy">
        <p class="demo-note">Fictional preview · Nothing sent or saved</p>
        <h1>{artist.name}</h1>
        <p class="exposure">Appears on {artist.days} · Not a preference rating.</p>
      </div>
      <img class="hero-art" src="/design-review/artist-light-waves-431.png" width="178" height="178" alt="" aria-hidden="true" />
    </header>

    <section class="step" aria-label="Current artist review step">
      {#if step === 'intro'}
        <h2 bind:this={stepHeading} tabindex="-1">Find the right artist.</h2>
        <p class="step-description">See possible matches for this name, then choose one or leave it unresolved.</p>
        <div class="step-actions">
          <button type="button" class="primary" on:click={preview}>Find matches</button>
          <button type="button" class="secondary" on:click={next}>{index === artists.length - 1 ? 'Return to first artist' : 'Skip for now'}</button>
        </div>
      {:else if step === 'consent'}
        <h2 bind:this={stepHeading} tabindex="-1">Before we search.</h2>
        <p class="step-description">Each real lookup would require your permission. This demo contacts nobody.</p>
        <div class="consent-note">
          <p><strong>Artist name:</strong> {artist.name}</p>
          <p><strong>Example catalog:</strong> DemoCatalog (fictional)</p>
          <p>A future real provider could see your IP address and retain the search. It would not receive your Apple export, listening dates, or account data.</p>
        </div>
        <div class="step-actions">
          <button type="button" class="primary" on:click={revealResults}>Show fictional matches</button>
          <button type="button" class="secondary" on:click={cancelPreview}>Cancel</button>
        </div>
      {:else if step === 'results'}
        <h2 bind:this={stepHeading} tabindex="-1">Which one is the right match?</h2>
        <p class="step-description">These are invented examples. Identical artist names do not prove identical identities.</p>
        <fieldset class="options">
          <legend>Choose one possible match</legend>
          {#each row.results as candidateIndex (candidateIndex)}
            <label class:chosen={row.chosen === candidateIndex}>
              <input type="radio" name="fictional-candidate" value={candidateIndex}
                checked={row.chosen === candidateIndex} on:change={() => chooseCandidate(candidateIndex)} />
              <span><strong>{candidates[candidateIndex].name}</strong><small>{candidates[candidateIndex].note}</small></span>
            </label>
          {/each}
        </fieldset>
        <div class="step-actions">
          <button type="button" class="primary" disabled={row.chosen === null} on:click={confirm}>Confirm fictional match</button>
          <button type="button" class="secondary" on:click={unsure}>None look right / I'm not sure</button>
        </div>
        <details class="optional-action">
          <summary>Other options</summary>
          <button type="button" class="text-action" on:click={preview}>Search again (fictional)</button>
        </details>
      {:else if step === 'done'}
        {#if row.decision === 'accepted'}
          <h2 bind:this={stepHeading} tabindex="-1">Match selected.</h2>
          <p class="step-description"><strong>{row.chosen === null ? 'Unverified' : candidates[row.chosen].name}</strong> is selected for this fictional session only. This is not verified identity or a preference rating.</p>
          <div class="step-actions">
            <button type="button" class="primary" on:click={next}>{index === artists.length - 1 ? 'Return to first artist' : 'Continue to next artist'}</button>
            <button type="button" class="secondary" on:click={undo}>Undo this match</button>
          </div>
        {:else}
          <h2 bind:this={stepHeading} tabindex="-1">Left unresolved.</h2>
          <p class="step-description">No match was assumed. You can come back to this name later.</p>
          <div class="step-actions">
            <button type="button" class="primary" on:click={next}>{index === artists.length - 1 ? 'Return to first artist' : 'Continue to next artist'}</button>
            <button type="button" class="secondary" on:click={preview}>Try this artist again</button>
          </div>
        {/if}
      {/if}
    </section>
    <footer class="review-bottom">
      <div class="review-utility">
        {#if index > 0}
          <button type="button" class="text-action" on:click={() => navigate(index - 1)}>Previous artist</button>
        {:else}
          <span class="utility-spacer" aria-hidden="true"></span>
        {/if}
        <details class="details-panel">
          <summary>How matching works &amp; privacy</summary>
          <div class="details-body">
            <p>This is an offline demonstration with invented artists. No real catalog connection. Nothing saved.</p>
            <p>Any future lookup would need separate permission per artist. Selecting a match is not a like or dislike.</p>
            <p class="tally">{count} of {artists.length} matched in this fictional session.</p>
            <button type="button" class="text-action" on:click={restart}>Start over</button>
          </div>
        </details>
      </div>
      <p class="sr-only" aria-live="polite" aria-atomic="true">{announcement}</p>
    </footer>
  </div>
</main>

<style>
  /* #431 Quiet Atlas: one task, one obvious action, optional detail. */
  .artist-review {
    --ink:#eaf0e7; --muted:#b8c7b8; --gold:#e0c89b;
    --line:rgba(210,225,207,.16);
    box-sizing:border-box; container-type:inline-size; width:100%;
    max-width:1160px; min-height:100%; margin-inline:auto;
    padding:clamp(24px,4vw,48px) clamp(18px,3.2vw,48px) 52px;
    color:var(--ink); background:radial-gradient(ellipse at 86% 7%,rgba(128,148,113,.07),transparent 46%),#101b15;
    font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }
  .artist-review * {box-sizing:border-box;}
  .review-container {width:100%;max-width:700px;margin-inline:auto;}
  .review-top {display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;
    padding-bottom:clamp(20px,4cqw,38px);border-bottom:1px solid var(--line);}
  .review-ident {color:var(--muted);font-size:14px;font-weight:600;}
  .close-link {display:inline-flex;align-items:center;min-height:44px;color:var(--muted);font-size:14px;text-decoration:none;padding:8px 0;}
  .close-link:hover,.text-action:hover,.secondary:hover {color:var(--gold);}
  .review-hero {margin-top:clamp(26px,4cqw,44px);}
  .review-hero {display:flex;align-items:flex-start;justify-content:space-between;gap:24px;}
  .hero-copy {min-width:0;flex:1;}
  .demo-note {margin:0 0 12px;font-size:13px;color:var(--muted);}
  h1 {font:400 clamp(34px,5cqw,46px)/1.12 Georgia,"Times New Roman",serif;letter-spacing:-.035em;overflow-wrap:anywhere;margin:0 0 14px;}
  .exposure {margin:0;max-width:510px;font-size:15px;line-height:1.7;color:var(--muted);}
  .hero-art {display:block;flex:0 0 auto;width:clamp(70px,12cqw,100px);height:auto;aspect-ratio:1;object-fit:contain;opacity:.88;border-radius:4px;}
  .step {width:100%;margin-top:clamp(30px,5cqw,52px);padding-top:clamp(22px,4cqw,30px);border-top:1px solid var(--line);}
  h2 {margin:0 0 12px;font:400 clamp(24px,3.7cqw,29px)/1.25 Georgia,"Times New Roman",serif;letter-spacing:-.02em;}
  h2:focus-visible {outline:2px solid #d5e7bd;outline-offset:4px;}
  .step-description {margin:0 0 22px;max-width:590px;color:var(--muted);font-size:16px;line-height:1.7;}
  .step-description strong {color:var(--ink);font-weight:600;}
  .step-actions {display:flex;flex-direction:column;align-items:flex-start;gap:6px;max-width:510px;}
  .primary {display:flex;align-items:center;justify-content:center;min-height:52px;width:100%;
    padding:13px 20px;border:1px solid transparent;border-radius:3px;
    background:#e2d1ac;color:#19271d;font-family:inherit;font-size:16px;font-weight:600;line-height:1.4;
    text-align:center;cursor:pointer;}
  .primary:not(:disabled):hover {background:#efe0bd;}
  .primary:disabled {opacity:.47;cursor:not-allowed;}
  .secondary,.text-action {display:inline-flex;align-items:center;justify-content:flex-start;min-height:44px;
    padding:9px 2px;color:var(--ink);border:0;background:transparent;
    font:500 15px/1.45 system-ui,sans-serif;text-align:left;cursor:pointer;}
  .consent-note {max-width:600px;margin:0 0 24px;padding:18px 20px;background:rgba(79,110,86,.15);border-left:2px solid #c8b485;}
  .consent-note p {margin:0 0 9px;font-size:15px;line-height:1.65;color:var(--muted);}
  .consent-note p:last-child {margin:12px 0 0;}
  .consent-note strong {font-weight:600;color:var(--ink);}
  .options {min-width:0;margin:0 0 23px;padding:0;border:0;max-width:600px;}
  .options legend {margin-bottom:9px;font-size:14px;color:var(--muted);}
  .options label {display:flex;align-items:center;gap:15px;min-height:74px;padding:15px 17px;margin-bottom:9px;
    border:1px solid var(--line);background:rgba(82,112,88,.1);cursor:pointer;}
  .options label.chosen {border-color:var(--gold);background:rgba(196,169,111,.1);}
  .options input {flex:0 0 20px;width:20px;height:20px;accent-color:#e2d1ac;cursor:pointer;}
  .options label span {min-width:0;overflow-wrap:anywhere;}
  .options strong,.options small {display:block;}
  .options strong {font-size:16px;font-weight:600;line-height:1.45;}
  .options small {color:var(--muted);font-size:14px;line-height:1.5;margin-top:4px;}
  .optional-action {margin-top:6px;max-width:510px;}
  .optional-action summary,.details-panel summary {display:inline-flex;align-items:center;min-height:44px;
    cursor:pointer;color:var(--muted);font-size:14px;padding:8px 0;}
  .optional-action summary:hover,.details-panel summary:hover {color:var(--gold);}
  .optional-action summary::after,.details-panel summary::after {content:'+';display:inline-block;margin-left:10px;font-size:18px;line-height:1;font-weight:400;}
  .optional-action[open] summary::after,.details-panel[open] summary::after {content:'−';}
  .optional-action .text-action {display:flex;}
  .review-bottom {margin-top:clamp(32px,5cqw,58px);padding-top:20px;border-top:1px solid var(--line);}
  .review-utility {display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;}
  .utility-spacer {min-width:8px;}
  .details-panel {margin-left:auto;max-width:100%;}
  .details-body {max-width:520px;padding:5px 0 12px;}
  .details-body p {font-size:14px;line-height:1.7;color:var(--muted);margin:0 0 12px;}
  .details-body .tally {color:var(--ink);}
  button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible {outline:3px solid #d5e7bd;outline-offset:3px;}
  .sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
    clip:rect(0,0,0,0);white-space:nowrap;border:0;}
  @container (max-width:650px) {
    .review-hero {gap:16px;}
    .hero-art {width:clamp(58px,14cqw,78px);}
    h1 {font-size:clamp(31px,6.2cqw,39px);}
    .step-description {font-size:15px;}
  }
  @container (max-width:420px) {
    .review-hero {gap:12px;}
    .hero-art {width:60px;}
    .review-ident,.close-link {font-size:14px;}
    .consent-note {padding:16px;}
    .review-utility {gap:6px;}
    .details-panel {margin-left:0;}
    h1 {font-size:clamp(31px,8.3cqw,36px);}
  }
  @media (max-width:700px) {.artist-review {padding-inline:18px;}}
  @media (max-width:360px) {.artist-review {padding-inline:15px;}}
  @media (prefers-reduced-motion:reduce) {
    .artist-review *,.artist-review *::before,.artist-review *::after {
      scroll-behavior:auto !important;animation:none !important;transition:none !important;
    }
  }
</style>
