<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { fixtureStatusLabel } from '$lib/quietAtlas/lightingModel.js'
  import { canDraftBrightness, reviewBrightnessDraft } from '$lib/quietAtlas/controlDraft.js'

  /** Selected group returned by buildLightingOverview(). */
  export let group
  /** @type {'disconnected'|'unverified'|'recent-read'|'stale-read'} */
  export let snapshotStatus = 'unverified'
  export let onClose = () => {}

  /** @type {Record<string,number>} */
  let draftPercents = {}
  /** @type {string | null} */
  let selectedFixtureId = null
  $: selectedFixture = group.fixtures.find((item) => item.id === selectedFixtureId)
  $: reviewedDraft = selectedFixture
    ? reviewBrightnessDraft(selectedFixture, snapshotStatus, draftPercents[selectedFixture.id])
    : null
  // A REST receipt is not telemetry authority. Drop old local choices whenever
  // that receipt becomes stale or the connection is unavailable.
  $: if (snapshotStatus !== 'recent-read') { draftPercents = {}; selectedFixtureId = null }

  /** @param {string} fixtureId @param {number} percent */
  function updateDraft(fixtureId, percent) {
    draftPercents = { ...draftPercents, [fixtureId]: percent }
    selectedFixtureId = null
  }

  async function dismissBrightnessReview() {
    const id = selectedFixtureId
    selectedFixtureId = null
    await tick()
    const review = [...(panel?.querySelectorAll('button.review') ?? [])]
      .find((button) => button instanceof HTMLButtonElement && button.dataset.fixtureId === id)
    if (review instanceof HTMLButtonElement && !review.disabled) review.focus()
    else closeButton?.focus()
  }

  /** @type {HTMLElement | null} */
  let panel
  /** @type {HTMLButtonElement | null} */
  let closeButton
  /** @type {HTMLElement | null} */
  let priorFocus

  const stopFocusOutside = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
    if (event.key !== 'Tab' || !panel) return
    const tabbable = [...panel.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), [tabindex]:not([tabindex="-1"])')].filter((element) => element instanceof HTMLElement)
    if (!tabbable.length) { event.preventDefault(); return }
    const first = tabbable[0], last = tabbable[tabbable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  onMount(() => { priorFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null; closeButton?.focus() })
  onDestroy(() => { if (priorFocus?.isConnected && typeof priorFocus.focus === 'function') priorFocus.focus() })
</script>

<svelte:window on:keydown={stopFocusOutside} />
<div class="sheet-root">
  <button class="sheet-scrim" type="button" aria-label={`Close ${group.label} details`} on:click={onClose}></button>
  <section bind:this={panel} class="sheet" role="dialog" aria-modal="true" aria-label={`${group.label} lighting details`}>
    <header class="sheet-header">
      <div><div class="overline">LIGHTING · FIXTURES</div><h2>{group.label}</h2></div>
      <button bind:this={closeButton} type="button" class="close" on:click={onClose} aria-label="Close lighting details">✕</button>
    </header>
    {#if snapshotStatus !== 'recent-read'}
      <p class="caution" role="status">Fixture values are historical, not confirmed live. Light snapshot: {snapshotStatus === 'disconnected' ? 'disconnected' : snapshotStatus === 'stale-read' ? 'stale' : 'unverified'}.</p>
    {:else if group.status === 'unknown' || group.status === 'partial' || group.status === 'offline'}
      <p class="caution" role="status">Not all fixture states are available. Unknown and offline lights cannot be assumed off.</p>
    {/if}
    <p class="explain">Individual fixtures are shown separately. The grouping on Home does not create a new group command.</p>
    <div class="fixtures">
      {#each group.fixtures as fixture (fixture.id)}
        <article class="fixture">
          <div class="fixture-top">
            <div><h3>{fixture.name}</h3><p class="sub">{snapshotStatus === 'recent-read' ? fixtureStatusLabel(fixture) : 'Last reported: ' + fixtureStatusLabel(fixture)}</p></div>
            <span class:lit={snapshotStatus === 'recent-read' && fixture.on === true} class="bulb" aria-hidden="true">●</span>
          </div>
          <label for={`fixture-brightness-${fixture.id}`}>Draft brightness <span>{canDraftBrightness(fixture, snapshotStatus) ? `${draftPercents[fixture.id] ?? fixture.brightness}%` : 'Unavailable'}</span></label>
          <input id={`fixture-brightness-${fixture.id}`} type="range" min="1" max="100" step="1"
            value={draftPercents[fixture.id] ?? fixture.brightness ?? 1}
            disabled={!canDraftBrightness(fixture, snapshotStatus)}
            on:input={(event) => updateDraft(fixture.id, Number(event.currentTarget.value))}
            aria-label={`Draft ${fixture.name} brightness percentage — no command sent`} />
          <button type="button" class="review" data-fixture-id={fixture.id} disabled={!reviewBrightnessDraft(fixture, snapshotStatus, draftPercents[fixture.id])}
            on:click={() => selectedFixtureId = fixture.id}>Review adjustment</button>
          <div class="palette-label">Color &amp; temperature</div>
          <div class="palette" role="group" aria-label={`Color options for ${fixture.name} unavailable in read-only review`}>
            <span class="swatch warm"></span><span class="swatch neutral"></span><span class="swatch cool"></span><span class="swatch lavender"></span>
          </div>
        </article>
      {/each}
    </div>
    {#if reviewedDraft}
      <div class="draft-summary" role="status">
        <strong>Proposed adjustment · not sent</strong>
        <p>{reviewedDraft.name}: {reviewedDraft.fromPercent}% → {reviewedDraft.toPercent}% (Hue brightness {reviewedDraft.proposedBri}/254).</p>
        <p>Future Apply must use the existing per-light manual-ownership path, recheck actual fixture availability, and refetch after acknowledgement. No group command is implied.</p>
        <button type="button" class="dismiss-review" on:click={dismissBrightnessReview}>Dismiss review</button>
      </div>
    {/if}
    <p class="readonly" role="note">You can draft an adjustment for a currently reported, reachable, on fixture. Nothing is sent to HomeHub. Power, color and actual Apply are unavailable pending the separately reviewed actuation path.</p>
    {#if group.id === 'kitchen'}
      <p class="pair">The kitchen pendants operate together in functional activities, but may differ in custom or atmospheric scenes. Their actual states are shown separately.</p>
    {/if}
  </section>
</div>

<style>
  .sheet-root { position:fixed;inset:0;z-index:510;display:flex;align-items:flex-end;justify-content:center; }
  .sheet-scrim { position:absolute;inset:0;border:0;background:rgba(4,10,8,.76);cursor:pointer; }
  .sheet { position:relative;box-sizing:border-box;outline:0;width:min(100%,620px);max-height:min(92dvh,900px);overflow:auto;overscroll-behavior:contain;background:#13221b;border:1px solid #526a56;border-radius:24px 24px 0 0;padding:24px 20px calc(26px + env(safe-area-inset-bottom,0px));color:#f2f0e8;box-shadow:0 0 60px #0008; }
  .sheet-header,.fixture-top { display:flex;justify-content:space-between;gap:16px;align-items:flex-start; }
  .overline { text-transform:uppercase;letter-spacing:.14em;color:#a1c2aa;font-size:11px;font-weight:700; }
  h2 { font:normal 35px Georgia,serif;margin:5px 0 12px; }
  h3 {font-size:16px;margin:0 0 5px;}p {line-height:1.48;} .sub {margin:0;color:#b2c5b5;font-size:13px;}
  .close {flex:0 0 44px;height:44px;border:1px solid #58715e;border-radius:50%;background:#1c3026;color:#fff;font-size:17px;cursor:pointer;}
  .caution {padding:12px 14px;background:#413726;border:1px solid #9e7948;border-radius:12px;color:#ffe6b4;}
  .explain {font-size:13px;color:#c0cdc0;margin:4px 0 20px;}
  .fixtures {display:grid;gap:12px;}
  .fixture {border:1px solid #3d5947;border-radius:17px;background:#1b2d23;padding:17px;}
  .bulb{color:#607967;font-size:21px;} .bulb.lit{color:#d9b77a;text-shadow:0 0 15px #b58d54;}
  label {display:flex;justify-content:space-between;font-size:12px;color:#d9e3d8;margin-top:19px;}
  input[type=range] {width:100%;margin:12px 0;accent-color:#a8c4a2;} input:disabled {opacity:.55;}
  .review,.dismiss-review {min-height:44px;padding:10px 14px;border:1px solid #77907a;border-radius:10px;background:#253d2f;color:#edf1e7;font:inherit;font-size:12px;cursor:pointer;}
  .review:disabled {opacity:.5;cursor:not-allowed;}
  .draft-summary {border:1px solid #b49d69;background:#352e21;border-radius:14px;margin-top:16px;padding:14px;color:#f2e6c6;}
  .draft-summary strong {display:block;font-size:14px;}
  .draft-summary p {font-size:12px;line-height:1.5;margin:9px 0;}
  .dismiss-review {background:#443828;border-color:#a99467;}
  .palette-label {font-size:12px;color:#b3c5b6;margin:3px 0 9px;}
  .palette{display:flex;gap:10px;opacity:.52;}
  .swatch {width:31px;height:31px;border-radius:50%;border:1px solid #ffffff55;}
  .warm{background:#dba170;}.neutral{background:#f5dcad;}.cool{background:#a7d6ed;}.lavender{background:#ba9fcb;}
  .readonly,.pair {font-size:12px;color:#d6c7a8;margin:17px 2px 0;}
  .pair{color:#b7c9b9;}
  button:focus-visible {outline:3px solid #d7e7bc;outline-offset:3px;}
  @media(min-width:800px){.sheet-root{align-items:center}.sheet{border-radius:24px;padding:30px;max-height:82dvh}.fixtures{grid-template-columns:repeat(2,minmax(0,1fr));}}
  @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
