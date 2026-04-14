<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiPost } from '$lib/api.js'
  import ApartmentViz from './ApartmentViz.svelte'
  import LightGrid from './LightGrid.svelte'
  import SceneBrowser from './SceneBrowser.svelte'
  import TryItOverlay from './TryItOverlay.svelte'

  /** @type {Record<string, any> | null} */
  let previewLightStates = null

  let tryItActive = false
  let tryItSceneName = ''
  let tryItRemaining = 0
  /** @type {ReturnType<typeof setInterval> | null} */
  let tryItTimer = null

  /** Desktop detection for apartment viz */
  let isDesktop = true
  /** @type {MediaQueryList | null} */
  let mql = null

  onMount(() => {
    mql = window.matchMedia('(min-width: 768px)')
    isDesktop = mql.matches
    const handler = (/** @type {MediaQueryListEvent} */ e) => { isDesktop = e.matches }
    mql.addEventListener('change', handler)
    return () => mql?.removeEventListener('change', handler)
  })

  onDestroy(() => {
    if (tryItTimer) clearInterval(tryItTimer)
  })

  function handlePreview(lightStates) {
    previewLightStates = lightStates
  }

  function handlePreviewEnd() {
    previewLightStates = null
  }

  async function handleTryIt(sceneId, sceneName) {
    if (tryItActive) return
    try {
      const resp = await apiPost(`/api/scenes/${sceneId}/try`, {})
      if (resp.status === 'ok') {
        tryItActive = true
        tryItSceneName = sceneName
        tryItRemaining = resp.revert_after || 30
        previewLightStates = null // clear any hover preview

        if (tryItTimer) clearInterval(tryItTimer)
        tryItTimer = setInterval(() => {
          tryItRemaining -= 1
          if (tryItRemaining <= 0) {
            clearInterval(tryItTimer)
            tryItTimer = null
            tryItActive = false
            tryItSceneName = ''
          }
        }, 1000)
      }
    } catch {
      /* activation failed, ignore */
    }
  }

  async function handleCancelTryIt() {
    try {
      await apiPost('/api/scenes/try/cancel', {})
    } catch {
      /* ignore */
    }
    if (tryItTimer) clearInterval(tryItTimer)
    tryItTimer = null
    tryItActive = false
    tryItSceneName = ''
    tryItRemaining = 0
  }
</script>

<div class="apartment-widget">
  {#if isDesktop}
    <div class="viz-section">
      <ApartmentViz {previewLightStates} {tryItActive} />
      {#if tryItActive}
        <TryItOverlay
          sceneName={tryItSceneName}
          remainingSeconds={tryItRemaining}
          onCancel={handleCancelTryIt}
        />
      {/if}
    </div>
  {/if}

  <div class="lights-section">
    <LightGrid />
  </div>

  <div class="scenes-section">
    <SceneBrowser
      onPreview={handlePreview}
      onPreviewEnd={handlePreviewEnd}
      onTryIt={handleTryIt}
      {tryItActive}
    />
  </div>
</div>

<style>
  .apartment-widget {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .viz-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .lights-section {
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    padding-top: 12px;
  }

  .scenes-section {
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    padding-top: 12px;
  }
</style>
