<script>
  import { onMount, onDestroy } from 'svelte'
  import { filterScenes, normalizeSceneList } from '$lib/quietAtlas/lightingModel.js'

  export let sceneList = []
  export let loading = false
  export let error = ''
  export let connected = false
  /** @type {string | null} */
  export let selectedSceneId = null
  export let onClose = () => {}
  export let onRetry = () => {}

  let category = 'all'
  let search = ''
  /** @type {HTMLElement | null} */
  let panel
  /** @type {HTMLButtonElement | null} */
  let closeButton
  /** @type {HTMLElement | null} */
  let previousFocus
  $: visible = filterScenes(sceneList, { category, search })

  const categories = [
    { id: 'all', label: 'All' }, { id: 'functional', label: 'Functional' },
    { id: 'cozy', label: 'Cozy' }, { id: 'moody', label: 'Moody' },
    { id: 'vibrant', label: 'Vibrant' }, { id: 'nature', label: 'Nature' },
    { id: 'entertainment', label: 'Entertainment' }, { id: 'social', label: 'Social' },
    { id: 'custom', label: 'Custom' }, { id: 'bridge', label: 'Hue' },
  ]
  function handleKeys(event) {
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return }
    if (event.key !== 'Tab' || !panel) return
    const tabbable = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href]')].filter((element) => element instanceof HTMLElement)
    const first = tabbable[0], last = tabbable[tabbable.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  onMount(() => {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const selected = normalizeSceneList(sceneList).find((s) => s.id === selectedSceneId)
    if (selected) { search = selected.name; category = 'all' }
    closeButton?.focus()
  })
  onDestroy(() => { if (previousFocus?.isConnected && typeof previousFocus.focus === 'function') previousFocus.focus() })
</script>

<svelte:window on:keydown={handleKeys} />
<div class="browser-root">
  <button class="scrim" aria-label="Close preset library" on:click={onClose} type="button"></button>
  <section bind:this={panel} class="browser" role="dialog" aria-modal="true" aria-label="Lighting preset library">
    <header><div><p class="eyebrow">LIGHTING · LIBRARY</p><h2>All presets</h2></div><button bind:this={closeButton} class="close" type="button" on:click={onClose} aria-label="Close preset library">✕</button></header>
    <p class="copy">Browse scenes reported by HomeHub. This read-only preview cannot apply them.</p>
    {#if !connected}<p class="warning" role="status">HomeHub is disconnected. Previously fetched scenes may be stale.</p>{/if}
    <label for="qa-scene-search">Search scenes</label>
    <input id="qa-scene-search" class="search" type="search" bind:value={search} placeholder="Name of a scene" />
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
          {#each visible as scene (scene.id)}
            <article class="scene">
              <h3>{scene.name}</h3>
              <p>{scene.source === 'preset' ? (scene.category || 'Curated') : scene.source === 'bridge' ? 'Hue bridge · freshness unverified' : 'Custom scene'}</p>
              <div class="disabled-note">Activation requires the existing HomeHub scene-control path.</div>
            </article>
          {/each}
        </div>
      {:else}<p class="notice">No scenes match this selection.</p>{/if}
    {/if}
    <p class="footer-note">Scene previews, timed Try It/cancel, custom editing, and effects remain in the existing Control experience until reviewed separately. No new scene writer is introduced here.</p>
  </section>
</div>
<style>
  .browser-root{position:fixed;inset:0;z-index:510;display:flex;justify-content:center;align-items:flex-end;}
  .scrim{position:absolute;inset:0;border:0;background:#040a08c9;cursor:pointer;}
  .browser{position:relative;box-sizing:border-box;width:min(100%,800px);max-height:95dvh;overflow:auto;overscroll-behavior:contain;background:#14221b;border:1px solid #536956;border-radius:24px 24px 0 0;padding:23px 18px calc(24px + env(safe-area-inset-bottom,0px));color:#f1f1e8;}
  header{display:flex;align-items:flex-start;justify-content:space-between;gap:15px;}.eyebrow{font-size:11px;color:#b5ceb0;letter-spacing:.13em;margin:0;font-weight:700;}
  h2{font:normal 34px Georgia,serif;margin:5px 0 14px;}.close{width:44px;height:44px;border:1px solid #536b59;border-radius:50%;background:#253b2d;color:#fff;cursor:pointer;}
  .copy,.footer-note{color:#b9cabd;font-size:13px;line-height:1.5;margin:0 0 18px;}.footer-note{margin-top:20px;}
  label{display:block;color:#dde9d9;font-size:12px;margin:0 0 7px;}.search{width:100%;height:46px;box-sizing:border-box;border:1px solid #5b7962;border-radius:10px;background:#223328;color:#fff;padding:0 14px;font:inherit;font-size:15px;}
  .filters{display:flex;gap:7px;overflow-x:auto;margin:17px 0;padding:1px 0 10px;scrollbar-width:thin;}
  .filters button{flex:0 0 auto;border:1px solid #526656;border-radius:999px;background:#24362a;color:#d6e4d3;padding:10px 15px;min-height:44px;cursor:pointer;font-size:13px;}
  .filters button.active{background:#a7c4a0;color:#10221a;border-color:#a7c4a0;font-weight:700;}
  .scene-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}.scene{border:1px solid #435c47;border-radius:14px;padding:15px;background:#213127;min-height:106px;box-sizing:border-box;}
  .scene h3{font-size:15px;margin:0 0 8px;overflow-wrap:anywhere;}.scene p{font-size:12px;color:#c2cdbb;text-transform:capitalize;margin:0 0 14px;}.disabled-note{font-size:11px;color:#cab999;line-height:1.5;}
  .notice,.warning{padding:15px;border:1px dashed #65816d;border-radius:12px;color:#bacfbe;}.warning{border-color:#a9895a;color:#f1d4a6;}.warning button{min-height:44px;padding:8px;border:1px solid #a9895a;color:#f1d4a6;background:none;cursor:pointer;}
  button:focus-visible,input:focus-visible{outline:3px solid #d1e9be;outline-offset:3px;}
  @media(min-width:800px){.browser-root{align-items:center}.browser{max-height:88dvh;border-radius:24px;padding:30px}.scene-grid{grid-template-columns:repeat(3,minmax(0,1fr));}}
  @media(max-width:340px){.scene-grid{grid-template-columns:1fr;}}
</style>
