<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import AssistedPlayAction from '$lib/components/AssistedPlayAction.svelte'
  import { appleMusicTrackId } from '$lib/assistedPlaybackAttempt.js'

  let input = ''
  /** @type {boolean | null} */
  let kiosk = null
  let approving = false
  let approvedId = ''
  let approvalMessage = ''
  const approvalEventIds = new Map()

  onMount(() => {
    void apiGet('/api/host/status')
      .then((status) => { kiosk = status?.can_control === true })
      .catch(() => { kiosk = false })
  })

  async function approveExact() {
    if (!trackId || kiosk !== true || approving || approvedId === trackId) return
    const identity = trackId
    const oldId = approvalEventIds.get(identity)
    const clientEventId = oldId || (
      globalThis.crypto?.randomUUID?.() || `music-trust-${Date.now()}-${Math.random().toString(16).slice(2)}`
    )
    approvalEventIds.set(identity, clientEventId)
    approving = true
    approvalMessage = ''
    try {
      const result = await apiPost('/api/music/trust/approval', {
        client_event_id: clientEventId,
        action: 'approve', provider: 'itunes_search', provider_id: identity,
      })
      if (result?.trust?.playback_eligible && result?.trust?.state === 'approved') {
        approvedId = identity
        if (trackId === identity) {
          approvalMessage = 'Exact track approval saved. Playback is still a separate action.'
        }
      } else if (trackId === identity) {
        approvalMessage = 'Approval was not confirmed. No playback was requested.'
      }
    } catch {
      if (trackId === identity) {
        approvalMessage = 'Approval outcome unknown. Retry would reuse the same event ID; no playback was requested.'
      }
    } finally {
      approving = false
    }
  }

  $: trackId = appleMusicTrackId(input)
  $: candidate = trackId
    ? {
        provider: 'itunes_search',
        provider_id: trackId,
        title: `Apple Music track ${trackId}`,
        playback_capable: true,
        playback_adapter: 'sonos_apple_music_share_link',
      }
    : null
</script>

<section class="approved-entry" aria-label="Explicit approved Apple Music playback">
  <div>
    <h3>Play an approved Apple Music track</h3>
    <p>Paste an Apple Music song link or exact track ID. HomeHub verifies the track and its approval before any playback. This does not start music automatically.</p>
  </div>
  <label for="approved-track-id">Apple Music song link or track ID</label>
  <input
    id="approved-track-id"
    type="text"
    bind:value={input}
    on:input={() => (approvalMessage = '')}
    autocomplete="off"
    placeholder="https://music.apple.com/…?i=1713833576"
  />
  {#if trackId && candidate}
    {#if kiosk === true}
      <div class="approval-controls">
        <button type="button" on:click={approveExact} disabled={approving || approvedId === trackId}>
          {approvedId === trackId ? 'Approval saved' : approving ? 'Saving approval…' : 'Approve this exact track'}
        </button>
        <small>Already approved? You can proceed directly to playback verification below.</small>
      </div>
      {#if approvalMessage}<small role="status">{approvalMessage}</small>{/if}
    {/if}
    {#key trackId}
      <AssistedPlayAction {candidate} explicitIdentity={true} />
    {/key}
  {:else if input.trim()}
    <small role="status">Enter a numeric track ID or an Apple Music song URL.</small>
  {/if}
  <small>Only previously approved/proven tracks can play. The Latitude kiosk is required; HomeHub enforces DND, Home/Awake, Sonos ownership, and volume policy.</small>
</section>

<style>
  .approved-entry {
    max-width: 1240px;
    width: calc(100% - 8px);
    margin: 0 auto;
    padding: 18px 20px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--bg-secondary);
    display: flex;
    flex-direction: column;
    gap: 9px;
  }
  h3 { margin: 0; color: var(--text-primary); font-size: 16px; }
  p { margin: 6px 0 4px; font-size: 12px; color: var(--text-muted); }
  label { font-size: 12px; color: var(--text-primary); }
  input {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 9px 11px;
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 13px;
  }
  small { font-size: 11px; color: var(--text-muted); }
  .approval-controls { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
  .approval-controls button {
    padding: 7px 11px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-primary);
    color: var(--text-primary);
    cursor: pointer;
    font-size: 12px;
  }
  .approval-controls button:disabled { opacity: .6; cursor: not-allowed; }
</style>
