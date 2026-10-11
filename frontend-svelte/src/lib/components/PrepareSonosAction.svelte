<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  let kiosk = null
  onMount(() => { void checkAccess() })

  async function checkAccess() {
    try {
      kiosk = (await apiGet('/api/host/status'))?.can_control === true
    } catch {
      kiosk = false
    }
  }

  let token = ''
  let expires = 0
  let busy = false
  let message = ''
  let track = ''

  async function preview() {
    if (busy || kiosk !== true) return
    busy = true
    token = ''
    try {
      const result = await apiGet('/api/music/prepare/preview')
      if (result.status === 'preview') {
        token = result.token
        expires = Date.now() + result.expires_in * 1000
        track = result.track
        message = 'Preview only. The current track will be discarded. Confirm within 45 seconds.'
      } else if (result.status === 'ready') {
        message = 'Sonos is already unloaded. Use the separate approved Play action below.'
      } else {
        message = `Preparation refused: ${String(result.reason || 'authority_unavailable').replaceAll('_', ' ')}.`
      }
    } catch {
      message = 'Preview unavailable. Recheck manually.'
    } finally { busy = false }
  }

  function cancelPreview() {
    token = ''
    message = 'Preparation canceled. No speaker changes were made.'
  }

  async function confirm() {
    if (busy || !token || kiosk !== true) return
    const confirmedToken = token
    token = ''
    if (Date.now() >= expires) {
      message = 'Preview expired. Recheck manually.'
      return
    }
    busy = true
    try {
      const result = await apiPost('/api/music/prepare/confirm', { token: confirmedToken })
      message = result.status === 'ready'
        ? 'Sonos unloaded and ready. Use the separate approved Play action below.'
        : `Sonos is not ready: ${String(result.reason || 'authority_unavailable').replaceAll('_', ' ')}. Recheck manually.`
    } catch {
      message = 'Preparation outcome unknown. No automatic retry. Recheck manually.'
    } finally { busy = false }
  }
</script>

{#if kiosk === null}
  <button type="button" on:click={checkAccess}>Check preparation access</button>
{:else if kiosk === true}
<section aria-label="Prepare Sonos for Playback">
  <h3>Prepare Sonos for Playback</h3>
  <p>For a paused loaded track with an empty queue. Preparation discards the current track; it does not play music or change volume.</p>
  <button type="button" disabled={busy} on:click={preview}>Preview / manually recheck</button>
  {#if token}
    <p>Loaded track: {track}. The current track will be discarded.</p>
    <button type="button" disabled={busy} on:click={confirm}>Confirm: discard current track</button>
    <button type="button" disabled={busy} on:click={cancelPreview}>Cancel preparation</button>
  {/if}
  {#if message}<p role="status" class="message">{message}</p>{/if}
</section>
{/if}

<style>
  section { max-width: 1240px; width: calc(100% - 8px); box-sizing: border-box; margin: 0 auto; padding: 18px 20px; border: 1px solid var(--border); border-radius: 14px; background: var(--bg-secondary); }
  h3 { margin: 0; color: var(--text-primary); font-size: 16px; }
  p { color: var(--text-muted); font-size: 12px; overflow-wrap: anywhere; }
  .message { color: var(--text-primary); font-size: 13px; padding: 10px 12px; background: var(--bg-primary); border-left: 3px solid var(--accent); border-radius: 6px; }
  button { padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-primary); color: var(--text-primary); cursor: pointer; }
  button:disabled { opacity: .6; cursor: not-allowed; }
</style>
