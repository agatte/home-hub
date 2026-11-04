<script>
  import { onMount } from 'svelte'
  import { recoverHold, saveHold, requestHold } from '$lib/hueAppHold.js'

  let state = null
  let busy = false
  let confirmed = false
  let storageAvailable = true
  let storage
  onMount(() => {
    try { storage = window.sessionStorage } catch { storageAvailable = false }
    state = recoverHold(storage)
  })

  async function act(releasing) {
    if (busy || (!releasing && (!confirmed || (state && state.kind !== 'released')))) return
    busy = true
    state = await requestHold(releasing, state)
    storageAvailable = saveHold(storage, state)
    confirmed = false
    busy = false
  }

  // 409 means the saved version is no longer releasable. Forgetting it is
  // local UI bookkeeping only; it never sends a light or ownership command.
  function forgetStaleToken() {
    if (busy || state?.kind !== 'conflict') return
    state = null
    confirmed = false
    storageAvailable = saveHold(storage, null)
  }
</script>

<details class="hue-hold">
  <summary>Hue app · L6 Hold / Release</summary>
  <p>Local prototype. Hold first, then use the Hue app. Hold does not turn Plant Wash on. It expires after four hours or an explicit Activity/mode change. HomeHub controls can replace this ownership.</p>
  <p>Keep this tab open until you release. If session storage fails, refreshing or closing loses the release token.</p>
  <div role="status" aria-live="polite">
    {#if state?.kind === 'acknowledged'}
      <p>Hold acknowledged. Current ownership is not monitored here.</p>
    {:else if state?.kind === 'unverified'}
      <p>Saved release token recovered — unverified. This does not prove a Hold is still active.</p>
    {:else if state?.kind === 'released'}
      <p>Release acknowledged. Normal automation may resume.</p>
    {:else if state?.kind === 'conflict'}
      <p>Ownership changed (409). No competing owner was released. Do not assume a Hold is active. You can discard this stale local token without changing the light.</p>
    {:else if state?.kind === 'uncertain'}
      <p>Outcome uncertain. Do not assume the Hold is active or released. No automatic retry.</p>
      {#if state.activeInMemory === true}<p>Server reported an in-memory owner; durability is uncertain.</p>{/if}
      {#if state.activeInMemory === false}<p>Server reported no in-memory owner; a durable Hold may still exist.</p>{/if}
      <p>After persistence recovers, explicitly release the saved token if available, or explicitly change Activity/mode to clear ownership. Without a token, do not create another Hold here.</p>
    {/if}
    {#if !storageAvailable}
      <p>Session storage unavailable. Keep this tab open: the release token is only in memory. Release here before leaving; closing or refreshing loses it. An explicit Activity/mode change can clear ownership.</p>
    {/if}
  </div>
  {#if !state || state.kind === 'released'}
    <label><input type="checkbox" bind:checked={confirmed} disabled={busy} /> Hold only L6 for Hue app use</label>
    <button type="button" disabled={busy || !confirmed} on:click={() => act(false)}>Hold L6</button>
  {/if}
  {#if state?.stamp}
    <button type="button" disabled={busy} on:click={() => act(true)}>Release saved L6 ownership</button>
  {/if}
  {#if state?.kind === 'conflict'}
    <button type="button" disabled={busy} on:click={forgetStaleToken}>Forget stale local token (no light change)</button>
  {/if}
  {#if busy}<p role="status">Waiting for acknowledgement…</p>{/if}
</details>

<style>
  .hue-hold { color: var(--text-muted); font-size: 14px; line-height: 1.5; padding: 6px 10px; min-width: 0; }
  summary { cursor: pointer; padding: 10px 0; min-height: 44px; box-sizing: border-box; }
  p { margin: 8px 0; }
  label { display: flex; gap: 8px; align-items: center; }
  button { display: block; margin-top: 8px; min-height: 44px; padding: 8px 12px; color: var(--text-primary); background: transparent; border: 1px solid var(--text-muted); border-radius: 8px; max-width: 100%; }
  button:disabled { opacity: 0.5; }
</style>
