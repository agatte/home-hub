<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { connected } from '$lib/stores/connection.js'
  import { lights } from '$lib/stores/lights.js'
  import { buildLightingOverview, normalizeSceneList } from '$lib/quietAtlas/lightingModel.js'
  import QuietAtlasLightingOverview from './QuietAtlasLightingOverview.svelte'
  import QuietAtlasGroupSheet from './QuietAtlasGroupSheet.svelte'
  import QuietAtlasSceneBrowser from './QuietAtlasSceneBrowser.svelte'

  /** @type {Array<Record<string, any>>} */
  let sceneList = []
  let scenesLoading = false
  let sceneError = ''
  /** @type {string | null} */
  let selectedGroupId = null
  let sceneBrowserOpen = false
  /** @type {string | null} */
  let focusSceneId = null
  let inflight = false
  let isMounted = false

  $: groups = buildLightingOverview($lights, $connected)
  $: selectedGroup = selectedGroupId ? groups.find((g) => g.id === selectedGroupId) : null

  async function refreshScenes() {
    if (inflight) return
    inflight = true
    scenesLoading = true
    sceneError = ''
    try {
      const result = await apiGet('/api/scenes')
      if (!Array.isArray(result?.scenes)) throw new Error('Scene response unavailable')
      if (isMounted) sceneList = result.scenes
    } catch {
      if (isMounted) { sceneList = []; sceneError = 'Could not load the HomeHub scene library.' }
    } finally {
      inflight = false
      if (isMounted) scenesLoading = false
    }
  }

  onMount(() => { isMounted = true; refreshScenes(); return () => { isMounted = false } })

  /** @param {string} id */
  function openGroup(id) { selectedGroupId = id }
  /** @param {string | null} [id] */
  function openScenes(id = null) { focusSceneId = id; sceneBrowserOpen = true }
  function browseScenes() { openScenes(); if (sceneError) refreshScenes() }
  /** @param {string} id */
  function openSpecificScene(id) { if (normalizeSceneList(sceneList).some((s) => s.id === id)) openScenes(id) }
</script>

<div class="qa-experience">
  <div class="review-banner" role="note"><strong>Quiet Atlas · development review</strong> — This experimental route reads light and scene information but cannot turn on lights, change brightness, apply scenes, or alter automation.</div>
  <QuietAtlasLightingOverview {sceneList} sceneLoading={scenesLoading} {sceneError}
    onOpenGroup={openGroup} onBrowseScenes={browseScenes} onOpenScene={openSpecificScene} />
  <div class="secondary-links">
    <a href="/">Existing HomeHub Home</a>
    <a href="/music">Music</a>
    <a href="/settings">Settings</a>
  </div>
</div>
{#if selectedGroup}
  <QuietAtlasGroupSheet group={selectedGroup} connected={$connected} onClose={() => selectedGroupId = null} />
{/if}
{#if sceneBrowserOpen}
  <QuietAtlasSceneBrowser {sceneList} loading={scenesLoading} error={sceneError} connected={$connected}
    selectedSceneId={focusSceneId} onRetry={refreshScenes} onClose={() => sceneBrowserOpen = false} />
{/if}

<style>
  .qa-experience { min-height: 100vh; max-width: 1100px; margin: 0 auto; padding: 20px clamp(14px, 4vw, 34px) 132px; box-sizing: border-box; }
  .review-banner { border: 1px solid #7b6742; color: #efdfb7; background: #312a1b; border-radius: 13px; padding: 13px 16px; font-size: 13px; line-height: 1.55; margin: 0 0 19px; }
  .secondary-links { display: flex; flex-wrap: wrap; gap: 17px; margin-top: 36px; }
  /* This route is nested inside the root app stacking context; global chrome
     would otherwise float in front of modal sheets on small screens. */
  :global(body:has(.sheet-root) .floating-nav),
  :global(body:has(.browser-root) .floating-nav),
  :global(body:has(.sheet-root) .vital-strip),
  :global(body:has(.browser-root) .vital-strip) { visibility: hidden; pointer-events: none; }
  .secondary-links a { color: #bed9bb; min-height: 44px; display: inline-flex; align-items: center; }
  a:focus-visible { outline: 3px solid #d8e6b8; outline-offset: 3px; }
</style>
