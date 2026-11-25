<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { normalizeSceneList } from '$lib/quietAtlas/lightingModel.js'
  import { sceneCards, sceneCardBackground } from '$lib/quietAtlas/sceneCards.js'
  import { reviewSceneDraft } from '$lib/quietAtlas/controlDraft.js'
  import QuietAtlasSceneApply from './QuietAtlasSceneApply.svelte'
  import QuietAtlasSceneTools from './QuietAtlasSceneTools.svelte'
  import QuietAtlasScenePreview from './QuietAtlasScenePreview.svelte'
  import CustomSceneEditor from './CustomSceneEditor.svelte'

  export let sceneList = []
  export let loading = false
  export let error = ''
  export let connected = false
  export let functional = false
  export let onApplied = () => {}
  let applying = false
  let toolsPending = false
  let editorOpen = false
  let editorPending = false
  /** @type {number | null} */
  let editingId = null
  $: busy = applying || toolsPending || editorPending
  function closeBrowser() { if (!busy) onClose() }
  /** @param {string | null} id */
  function openEditor(id = null) {
    if (!functional || !connected || loading || error || busy) return
    const match = id === null ? null : /^custom_(\d+)$/.exec(id)
    if (id !== null && !match) return
    editingId = match ? Number(match[1]) : null
    requestedReviewId = null
    editorOpen = true
  }
  function closeEditor() { if (!editorPending) editorOpen = false }
  function editorSaved() { editorOpen = false; requestedReviewId = null; onRetry() }
  /** @type {string | null} */
  export let selectedSceneId = null
  export let onClose = () => {}
  export let onRetry = () => {}

  let category = 'all'
  let search = ''
  /** @type {string | null} */
  let requestedReviewId = null
  $: reviewedScene = reviewSceneDraft(requestedReviewId, sceneList, { connected, loading, error })
  // Never resurrect a cached review after disconnect or a failed library read.
  $: if (!connected || loading || error) requestedReviewId = null
  /** @type {HTMLElement | null} */
  let panel
  /** @type {HTMLButtonElement | null} */
  let closeButton
  /** @type {HTMLElement | null} */
  let previousFocus
  const PAGE_SIZE = 12
  let visibleLimit = PAGE_SIZE
  $: { category; search; visibleLimit = PAGE_SIZE }
  $: visible = sceneCards(sceneList, { category, search })
  $: shown = visible.slice(0, visibleLimit)

  /** @param {string} id */
  async function chooseScene(id) {
    if (!connected || loading || error || busy || editorOpen) return
    requestedReviewId = id
    await tick()
    panel?.querySelector('.review-panel')?.scrollIntoView({block:'nearest'})
  }

  async function dismissSceneReview() {
    const id = requestedReviewId
    requestedReviewId = null
    await tick()
    const review = [...(panel?.querySelectorAll('button.scene-review') ?? [])]
      .find((button) => button instanceof HTMLButtonElement && button.dataset.sceneId === id)
    if (review instanceof HTMLButtonElement && !review.disabled) review.focus()
    else closeButton?.focus()
  }

  const categories = [
    { id: 'all', label: 'All' }, { id: 'functional', label: 'Functional' },
    { id: 'cozy', label: 'Cozy' }, { id: 'moody', label: 'Moody' },
    { id: 'vibrant', label: 'Vibrant' }, { id: 'nature', label: 'Nature' },
    { id: 'entertainment', label: 'Entertainment' }, { id: 'social', label: 'Social' },
    { id: 'custom', label: 'Custom' }, { id: 'bridge', label: 'Hue' },
  ]
  function handleKeys(event) {
    if (event.key === 'Escape') { event.preventDefault(); if (!busy) { if (editorOpen) closeEditor(); else closeBrowser() } return }
    if (event.key !== 'Tab' || !panel) return
    const tabbable = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, a[href]')]
      .filter((element) => element instanceof HTMLElement)
      .filter((element) => element.getClientRects().length > 0)
    const first = tabbable[0], last = tabbable[tabbable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  onMount(() => {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const selected = normalizeSceneList(sceneList).find((s) => s.id === selectedSceneId)
    if (selected) { search = selected.name; category = 'all'; if (functional) requestedReviewId = selected.id }
    closeButton?.focus()
  })
  onDestroy(() => { if (previousFocus?.isConnected && typeof previousFocus.focus === 'function') previousFocus.focus() })
</script>

<svelte:window on:keydown={handleKeys} />
<div class="browser-root">
  <button class="scrim" aria-label="Close preset library" on:click={closeBrowser} disabled={busy} type="button"></button>
  <section bind:this={panel} class="browser" role="dialog" aria-modal="true" aria-label="Lighting preset library">
    <header><div><p class="eyebrow">LIGHTING · LIBRARY</p><h2>All presets</h2></div><button bind:this={closeButton} class="close" type="button" on:click={closeBrowser} disabled={busy} aria-label="Close preset library">✕</button></header>
    <p class="copy">{functional ? 'Choose a scene to apply or preview, create your own, or explore Hue effects.' : 'Browse scenes reported by HomeHub. This read-only preview cannot apply them.'}</p>
    {#if !connected}<p class="warning" role="status">HomeHub is disconnected. Previously fetched scenes may be stale.</p>{/if}
    {#if functional}
      <div class="editor-toolbar">
        <button type="button" class="scene-review" disabled={!connected || loading || !!error || busy || editorOpen} on:click={() => openEditor()}>New custom scene</button>
      </div>
      {#if editorOpen}
        {#if !connected}<p class="warning" role="status">Reconnect before saving your scene.</p>{/if}
        <CustomSceneEditor {editingId} libraryOnly={true} available={connected} bind:saving={editorPending} onSave={editorSaved} onCancel={closeEditor} />
      {/if}
    {/if}
    <label for="qa-scene-search">Search scenes</label>
    <input id="qa-scene-search" class="search" type="search" bind:value={search} placeholder="Name of a scene" />
    <label class="mobile-category-label" for="qa-scene-category">Scene category</label>
    <select id="qa-scene-category" class="mobile-category-select" bind:value={category}>
      {#each categories as cat (cat.id)}
        <option value={cat.id}>{cat.label}</option>
      {/each}
    </select>
    <div class="filters" role="group" aria-label="Scene categories">
      {#each categories as cat (cat.id)}
        <button type="button" class:active={category === cat.id} aria-pressed={category === cat.id} on:click={() => category = cat.id}>{cat.label}</button>
      {/each}
    </div>
    {#if loading}<p class="notice" role="status">Loading scene names…</p>{/if}
    {#if error}<p class="warning" role="alert">{error} <button type="button" on:click={onRetry}>Retry</button></p>{/if}
    {#if !loading && !error}
      {#if visible.length}
        <div class="scene-grid">
          {#each shown as scene (scene.key)}
            <article class="scene" style:background={sceneCardBackground(scene.palette) || null} class:colored={scene.palette.length > 0}>
              {#if scene.palette.length}
                <div class="palette" aria-hidden="true" style:background={`linear-gradient(110deg, ${[...scene.palette, ...(scene.palette.length === 1 ? scene.palette : [])].join(', ')})`}></div>
              {/if}
              <div class="scene-heading">
                <h3>{scene.name}</h3>
                <p>{scene.source === 'preset' ? (scene.category || 'Curated') : scene.source === 'bridge' ? 'Hue bridge' : 'Custom scene'}</p>
              </div>
              {#if scene.variants.length > 1}
                <details class="variants">
                  <summary>{scene.variants.length} Hue versions</summary>
                  {#each scene.variants as variant (variant.id)}
                    <button class="scene-review variant" data-scene-id={variant.id} type="button" disabled={!connected || loading || !!error || busy || editorOpen} on:click={() => chooseScene(variant.id)}>{variant.label} <span aria-hidden="true">↗</span><span class="sr-only"> · {scene.name} · {variant.id.slice(-6)}</span></button>
                  {/each}
                </details>
              {:else}
                <button class="scene-review" data-scene-id={scene.id} type="button" disabled={!connected || loading || !!error || busy || editorOpen}
                  on:click={() => chooseScene(scene.id)}>{functional ? 'Choose scene' : 'Review preset impact'}</button>
              {/if}
              {#if functional && scene.source === 'custom'}
                <button type="button" class="scene-review edit-scene" disabled={!connected || loading || !!error || busy || editorOpen} on:click={() => openEditor(scene.id)}>Edit scene</button>
              {/if}
            </article>
          {/each}
        </div>
        <div class="library-summary"><span>Showing {shown.length} of {visible.length} scenes</span>{#if category === 'all' && !search}<span>Filter by category to find more</span>{/if}</div>
        {#if shown.length < visible.length}
          <button type="button" class="show-more" on:click={() => visibleLimit += PAGE_SIZE}>Show {Math.min(PAGE_SIZE, visible.length - shown.length)} more scenes</button>
        {/if}
      {:else}<p class="notice">No scenes match this selection.</p>{/if}
    {/if}
    {#if reviewedScene}
      <div class="review-panel" role="status">
        <strong>{reviewedScene.name}{functional ? '' : ' · review only'}</strong>
        <p>{reviewedScene.description}</p>
        {#if reviewedScene.previewRows}
          <QuietAtlasScenePreview rows={reviewedScene.previewRows} title="Saved scene apartment preview" />
        {/if}
        {#if reviewedScene.declaredTargets}
          <div class="declared-scope">
            <p><strong>Saved scene declaration · {reviewedScene.declaredTargets.length} lights</strong></p>
            <ul aria-label="Declared scene light targets">
              {#each reviewedScene.declaredTargets as target (target.id)}
                <li>{target.label}: {target.power}{target.power === 'On' ? ` · ${target.brightness}` : ''}</li>
              {/each}
            </ul>
          </div>
        {/if}
        <p>These are saved targets, not measured fixture states or guaranteed applied results. HomeHub's protected-light, scene and effect rules may change the final outcome.{#if !functional} Activation requires the separately reviewed safety path. No scene command has been sent.{/if}</p>
        <button type="button" disabled={busy} on:click={dismissSceneReview}>Dismiss review</button>
      </div>
    {/if}
    {#if functional}
      <QuietAtlasSceneApply scene={reviewedScene} connected={connected && !loading && !error && !toolsPending && !editorOpen} bind:pending={applying} {onApplied} />
      <QuietAtlasSceneTools scene={reviewedScene} {connected} blocked={applying || editorOpen} bind:pending={toolsPending} onChanged={onApplied} />
      <p class="footer-note">Save custom scenes before trying them. Previewing a saved scene uses HomeHub's timed restore rather than permanent manual light changes.</p>
    {:else}
      <p class="footer-note">Scene activation, Try It/cancel, custom editing, and effects remain in the existing Control experience until reviewed separately. This preview sends no device commands.</p>
    {/if}
  </section>
</div>
<style>
  .browser-root{position:fixed;inset:0;z-index:510;display:flex;justify-content:center;align-items:flex-end;}
  .scrim{position:absolute;inset:0;border:0;background:#040a08c9;cursor:pointer;}
  .browser{position:relative;box-sizing:border-box;width:min(100%,800px);max-height:95dvh;overflow:auto;overscroll-behavior:contain;background:var(--hh-panel-deep,#141c19);border:1px solid var(--hh-line,#536956);border-radius:24px 24px 0 0;padding:23px 18px calc(24px + env(safe-area-inset-bottom,0px));color:#f1f1e8;}
  header{display:flex;align-items:flex-start;justify-content:space-between;gap:15px;}.eyebrow{font-size:11px;color:#b5ceb0;letter-spacing:.13em;margin:0;font-weight:700;}
  h2{font:normal 34px Georgia,serif;margin:5px 0 14px;}.close{width:44px;height:44px;border:1px solid #536b59;border-radius:50%;background:var(--hh-control,#202a26);color:var(--hh-ink,#f1eee7);cursor:pointer;}
  .copy,.footer-note{color:#b9cabd;font-size:13px;line-height:1.5;margin:0 0 18px;}.footer-note{margin-top:20px;}
  label{display:block;color:#dde9d9;font-size:12px;margin:0 0 7px;}.search{width:100%;height:46px;box-sizing:border-box;border:1px solid #5b7962;border-radius:10px;background:var(--hh-control,#202a26);color:var(--hh-ink,#f1eee7);padding:0 14px;font:inherit;font-size:15px;}
  .mobile-category-label,.mobile-category-select{display:none;}
  .filters{display:flex;gap:7px;overflow-x:auto;margin:17px 0;padding:1px 0 10px;scrollbar-width:thin;}
  .filters button{flex:0 0 auto;border:1px solid #526656;border-radius:999px;background:#24362a;color:#d6e4d3;padding:10px 15px;min-height:44px;cursor:pointer;font-size:13px;}
  .filters button.active{background:var(--hh-accent,#e4c99e);color:#19201b;border-color:var(--hh-accent,#e4c99e);font-weight:700;}
  .library-summary{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px;color:#bacfbe;font-size:12px;margin:10px 0;}
  .scene-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-items:start;}
  .scene{display:flex;flex-direction:column;gap:8px;border:1px solid #536956;border-radius:14px;padding:12px;background:var(--hh-card-background,#1c2522);min-width:0;box-sizing:border-box;}
  .scene h3{font-size:15px;margin:0 0 4px;overflow-wrap:anywhere;}.scene p{font-size:12px;color:#d4dcd0;text-transform:capitalize;margin:0;}
  .palette{height:9px;border-radius:5px;opacity:.95;box-shadow:0 3px 14px rgba(0,0,0,.18);}
  .scene.colored{border-color:rgba(235,235,235,.25);}
  .scene .scene-review{background:rgba(12,15,19,.72);border-color:rgba(235,235,235,.32);color:#f1f1ee;}
  .scene .scene-review:hover:not(:disabled){background:rgba(12,15,19,.88);border-color:rgba(235,235,235,.60);}
  .scene.colored p{color:#e3e4e0;}
  .variants{min-width:0;}.variants summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:12px;color:#e6ece2;}.variants summary::before{content:'▸';margin-right:6px;}.variants[open] summary::before{content:'▾';}
  .variant{display:flex;justify-content:space-between;gap:4px;width:100%;margin-top:5px;overflow-wrap:anywhere;}
  .show-more{display:block;width:100%;margin-top:10px;min-height:44px;border:1px solid #719479;border-radius:10px;background:#253b2d;color:#ecf1e5;font:inherit;font-size:13px;cursor:pointer;}
  .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;}
  .scene-review,.review-panel button{min-height:44px;border:1px solid #7b967c;border-radius:10px;background:var(--hh-control,#202a26);color:var(--hh-ink,#f1eee7);padding:9px 11px;font-size:12px;cursor:pointer;}
  .editor-toolbar{margin-bottom:14px;}
  .scene-review:disabled{opacity:.5;cursor:not-allowed;}
  .review-panel{border:1px solid #a98e58;border-radius:14px;background:#392f21;color:#f1e3c4;margin:15px 0;padding:16px;}
  .review-panel strong{font-size:15px;}.review-panel p{font-size:12px;line-height:1.55;}
  .declared-scope{border:1px solid #8a7754;border-radius:10px;padding:10px 13px;margin:12px 0;background:#2c2c22;}
  .declared-scope ul{margin:9px 0 4px;padding-left:19px;display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:7px 18px;}
  .declared-scope li{font-size:12px;line-height:1.45;color:#eadfca;}
  .notice,.warning{padding:15px;border:1px dashed #65816d;border-radius:12px;color:#bacfbe;}.warning{border-color:#a9895a;color:#f1d4a6;}.warning button{min-height:44px;padding:8px;border:1px solid #a9895a;color:#f1d4a6;background:none;cursor:pointer;}
  button:focus-visible,input:focus-visible{outline:3px solid #d1e9be;outline-offset:3px;}
  @media(min-width:800px){.browser-root{align-items:center}.browser{max-height:88dvh;border-radius:24px;padding:30px}.scene-grid{grid-template-columns:repeat(3,minmax(0,1fr));}}
  /* A category picker replaces horizontal chip scrolling on phone-sized screens. */
  @media(max-width:700px){
    .browser { min-width:0; width:100%; max-height:95dvh; border-radius:20px 20px 0 0; padding:19px 16px calc(24px + env(safe-area-inset-bottom,0px)); }
    .browser h2 { font-size:29px; }
    .mobile-category-label { display:block; margin-top:14px; }
    .mobile-category-select { display:block; box-sizing:border-box; width:100%; min-height:48px; padding:10px 14px; border:1px solid #719479; border-radius:11px; background:var(--hh-control,#202a26); color:var(--hh-ink,#f1eee7); font:inherit; font-size:16px; }
    .filters { display:none; }
    .scene-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:10px; }
    .scene { min-width:0; padding:12px; }
    .scene h3 { font-size:15px; line-height:1.25; }
    .scene p { line-height:1.45; }
    .scene-review { min-height:44px; width:100%; font-size:12px; padding:8px; overflow-wrap:anywhere; }
    .review-panel { overflow-wrap:anywhere; }
    .declared-scope ul { grid-template-columns:minmax(0,1fr); }
    .footer-note { line-height:1.6; }
  }
  @media(max-width:350px){.scene-grid{grid-template-columns:minmax(0,1fr);}}
  .mobile-category-select:focus-visible{outline:3px solid #d1e9be;outline-offset:3px;}
</style>
