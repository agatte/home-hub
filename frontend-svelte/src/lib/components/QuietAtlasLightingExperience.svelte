<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { connected } from '$lib/stores/connection.js'
  import { newReadOnlySnapshot, connectionChanged, invalidateLightRead, beginLightRead, acceptLightRead, failLightRead, readStatus } from '$lib/quietAtlas/lightSnapshot.js'
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
  let lightReadFailures = 0
  let nextAutomaticLightReadAt = 0
  // Only the opt-in review reader is quiet; other error reporting is unchanged.
  /** @type {Set<AbortController>} */
  const lightReadControllers = new Set()
  function abortPendingLightReads() {
    for (const controller of lightReadControllers) controller.abort()
    lightReadControllers.clear()
  }
  /** @param {AbortSignal} signal */
  async function quietLightRead(signal) {
    const response = await fetch('/api/lights', { signal })
    if (!response.ok) throw new Error('Light read unavailable')
    return response.json()
  }
  let snapshot = newReadOnlySnapshot()
  let nowMs = Date.now()
  $: snapshotStatus = readStatus(snapshot, nowMs)
  // Groups and snapshot provenance derive from the SAME verified API response,
  // never from the globally optimistic WebSocket light store.
  $: groups = buildLightingOverview(/** @type {any} */ (snapshot.fixtures), snapshotStatus === 'recent-read')

  async function refreshLights() {
    if (!isMounted || !snapshot.connected || document.visibilityState !== 'visible') return
    const next = beginLightRead(snapshot)
    snapshot = next.state
    if (!next.ticket) return
    const ticket = next.ticket
    const controller = new AbortController()
    lightReadControllers.add(controller)
    const timeoutId = window.setTimeout(() => controller.abort(), 8000)
    try {
      const rows = await quietLightRead(controller.signal)
      if (isMounted && snapshot.generation === ticket.generation && snapshot.requestId === ticket.requestId) {
        nowMs = Date.now()
        snapshot = acceptLightRead(snapshot, ticket, rows, nowMs)
        // A completed but invalid response is a failed snapshot, not success.
        if (snapshot.receivedAt === nowMs) {
          lightReadFailures = 0
          nextAutomaticLightReadAt = 0
        } else {
          lightReadFailures = Math.min(3, lightReadFailures + 1)
          nextAutomaticLightReadAt = nowMs + 15000 * 2 ** lightReadFailures
        }
      }
    } catch {
      if (isMounted && snapshot.generation === ticket.generation && snapshot.requestId === ticket.requestId) {
        nowMs = Date.now()
        snapshot = failLightRead(snapshot, ticket)
        lightReadFailures = Math.min(3, lightReadFailures + 1)
        nextAutomaticLightReadAt = nowMs + 15000 * 2 ** lightReadFailures
      }
    } finally {
      window.clearTimeout(timeoutId)
      lightReadControllers.delete(controller)
    }
  }

  /** @param {boolean} available */
  function onConnectionChanged(available) {
    if (!isMounted) return
    abortPendingLightReads()
    snapshot = connectionChanged(snapshot, available)
    lightReadFailures = 0
    nextAutomaticLightReadAt = 0
    nowMs = Date.now()
    if (available && document.visibilityState === 'visible') void refreshLights()
  }

  function onVisibilityChanged() {
    if (!isMounted) return
    abortPendingLightReads()
    snapshot = invalidateLightRead(snapshot)
    nowMs = Date.now()
    if (document.visibilityState === 'visible' && snapshot.connected) void refreshLights()
  }
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

  onMount(() => {
    isMounted = true
    const unsubscribe = connected.subscribe(onConnectionChanged)
    document.addEventListener('visibilitychange', onVisibilityChanged)
    const ageTimer = window.setInterval(() => { nowMs = Date.now() }, 1000)
    // Poll for REST *read* provenance, never as a substitute for bulb telemetry.
    const refreshTimer = window.setInterval(() => {
      if (!snapshot.pending && snapshot.connected && document.visibilityState === 'visible' &&
          Date.now() >= nextAutomaticLightReadAt) void refreshLights()
    }, 15000)
    void refreshScenes()
    return () => {
      isMounted = false
      abortPendingLightReads()
      unsubscribe()
      document.removeEventListener('visibilitychange', onVisibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(refreshTimer)
    }
  })

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
  <QuietAtlasLightingOverview {groups} {snapshotStatus} onRefreshLights={refreshLights} {sceneList} sceneLoading={scenesLoading} {sceneError}
    onOpenGroup={openGroup} onBrowseScenes={browseScenes} onOpenScene={openSpecificScene} />
</div>
{#if selectedGroup}
  <QuietAtlasGroupSheet group={selectedGroup} {snapshotStatus} onClose={() => selectedGroupId = null} />
{/if}
{#if sceneBrowserOpen}
  <QuietAtlasSceneBrowser {sceneList} loading={scenesLoading} error={sceneError} connected={$connected}
    selectedSceneId={focusSceneId} onRetry={refreshScenes} onClose={() => sceneBrowserOpen = false} />
{/if}

<style>
  .qa-experience { max-width: 1100px; margin: 0 auto; padding: 20px clamp(14px, 4vw, 34px) 36px; box-sizing: border-box; }
  .review-banner { border: 1px solid #7b6742; color: #efdfb7; background: #312a1b; border-radius: 13px; padding: 13px 16px; font-size: 13px; line-height: 1.55; margin: 0 0 19px; }
  @media (max-width: 760px) {
    .qa-experience { padding: 10px clamp(12px, 4vw, 20px) 30px; }
    .review-banner { padding: 9px 11px; font-size: 11.5px; line-height: 1.4; margin-bottom: 12px; }
  }
</style>
