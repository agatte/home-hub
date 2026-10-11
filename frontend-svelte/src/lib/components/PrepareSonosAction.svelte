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

  const refusalMessages = {
    apartment_away: 'HomeHub reports the apartment Away. Preparation requires Home.',
    sleeping_active: 'HomeHub is Sleeping. Preparation is unavailable until the house is awake.',
    travel_mode_active: 'Travel Mode blocks preparation.',
    returning_home_active: 'Returning Home is still reconciling. Preparation is unavailable.',
    house_authority_unavailable: 'HomeHub cannot verify that the apartment is Home.',
    authority_unavailable: 'HomeHub cannot verify the required preparation authority.',
    dnd_active: 'Do Not Disturb is active. Preparation is unavailable.',
    tts_active: 'Spoken audio is active. Preparation will not interrupt it.',
    ambient_playback_owned: 'Ambient audio currently owns playback. Preparation will not interrupt it.',
    sonos_unavailable: 'Sonos is unavailable. Recheck when the speaker reconnects.',
    audio_ownership_unavailable: 'Audio ownership authority is unavailable. Preparation is blocked.',
    audio_ownership_busy: 'Another audio action owns the speaker. Preparation is blocked.',
    authority_changed: 'The preparation authority changed. Recheck before attempting again.',
    source_evidence_unavailable: 'Sonos source evidence is unavailable. Recheck manually when Sonos is available.',
    source_stopped_but_loaded: 'Sonos is stopped but still has a source loaded. Nothing was automatically unloaded. The separate supported paused-source preparation is unavailable in this state.',
    source_queue_not_empty: 'The Sonos queue is not empty. Preparation cannot discard queued music. Review the queue in Sonos before rechecking.',
    source_queue_evidence_unavailable: 'The Sonos queue could not be verified. Recheck manually; no queue changes were made.',
    source_unsupported_transport: 'This Sonos source is not supported for preparation. Review the source in Sonos; no changes were made.',
    source_playing: 'Sonos is playing. Preparation cannot interrupt playback. Recheck only when playback is no longer active.',
    source_missing_track_details: 'The paused source has no verified track details. Review the source in Sonos and recheck manually.',
    source_not_coordinator: 'This Sonos speaker is a group follower. Review the group in Sonos before rechecking.',
    source_play_mode_not_normal: 'Sonos is using a repeat or shuffle play mode. Review the play mode in Sonos before rechecking.',
    source_muted: 'Sonos is muted. Review mute in Sonos before rechecking; preparation does not change mute.',
    source_volume_zero: 'Sonos volume is zero. Review volume in Sonos before rechecking; preparation does not change volume.',
    source_not_eligible: 'This source is not eligible for preparation. Review Sonos and recheck manually.',
  }

  function refusalMessage(reason) {
    return Object.hasOwn(refusalMessages, reason)
      ? refusalMessages[reason]
      : 'Preparation is unavailable under the current source or house policy. Recheck manually.'
  }

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
        message = `Preparation refused: ${refusalMessage(result.reason)}`
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
        : `Sonos is not ready: ${refusalMessage(result.reason)}`
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
