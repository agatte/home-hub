<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { getAttempt, reserveAttempt, completeAttempt, beginAnotherAttempt } from '$lib/assistedPlaybackAttempt.js'

  /** @type {any} */
  export let candidate
  /** @type {any} */
  export let trust = null
  export let explicitIdentity = false

  /** @type {boolean | null} */
  let kiosk = null
  let checking = false
  let confirming = false
  let sending = false
  let guardMessage = ''
  let details = ''
  /** @type {string | null} */
  let eventId = null
  /** @type {any | null} */
  let result = null
  let uncertain = false

  $: identity = candidate?.provider === 'itunes_search' && /^\d{5,20}$/.test(String(candidate?.provider_id || ''))
    ? `itunes_search:${candidate.provider_id}` : ''
  $: eligible = !!identity
    && candidate?.playback_capable === true
    && candidate?.playback_adapter === 'sonos_apple_music_share_link'
    && (explicitIdentity || (trust?.playback_eligible === true
      && ['approved', 'proven'].includes(trust?.state)))
  $: if (!eligible) confirming = false

  onMount(() => {
    const prior = identity ? getAttempt(identity) : null
    if (prior) {
      eventId = prior.clientEventId
      if (prior.status === 'pending' || prior.status === 'unknown') uncertain = true
      else result = { status: prior.status, reason: prior.reason }
    }
    // The existing strict playback endpoint accepts only direct localhost
    // without an API key. Do not send a token or weaken LAN authentication.
    void apiGet('/api/host/status')
      .then((status) => { kiosk = status?.can_control === true })
      .catch(() => { kiosk = false })
  })

  function newEventId() {
    const id = globalThis.crypto?.randomUUID?.()
    return id ? `music-assisted-${id}`
      : `music-assisted-${Date.now()}-${Math.random().toString(16).slice(2)}`
  }

  async function prepare() {
    if (!eligible || kiosk !== true || checking || sending || eventId) return
    checking = true
    confirming = false
    guardMessage = ''
    details = ''
    try {
      const [host, activity, sonos, curves, capability] = await Promise.all([
        apiGet('/api/host/status'),
        apiGet('/api/automation/status'),
        apiGet('/api/sonos/status'),
        apiGet('/api/automation/mode-volume'),
        apiGet('/api/music/assisted-playback/status'),
      ])
      const mode = String(activity?.current_mode || '').toLowerCase()
      const period = activity?.time_period === 'late_night' ? 'night' : activity?.time_period
      const target = curves?.[mode]?.[period || 'day']
      if (host?.mode !== 'HOME' || host?.can_control !== true || activity?.house_state !== 'home') {
        guardMessage = 'Use the Latitude kiosk while HomeHub is Home.'
      } else if (activity?.dnd_enabled || ['idle', 'away', 'sleeping', ''].includes(mode)) {
        guardMessage = 'Playback is unavailable in the current activity or DND state.'
      } else if (!capability?.enabled || !capability?.explicit_only || !capability?.actuation_allowed) {
        guardMessage = 'Assisted playback is not currently available.'
      } else if (!['STOPPED', 'NO_MEDIA_PRESENT'].includes(sonos?.state) || sonos?.track || sonos?.mute) {
        guardMessage = 'Sonos must be stopped, unmuted, and have no loaded track.'
      } else if (!Number.isInteger(target) || Number(sonos?.volume) !== target || target <= 0) {
        guardMessage = Number.isInteger(target)
          ? `For ${mode} / ${period}, Sonos must already be at volume ${target}. Current: ${sonos?.volume}.`
          : 'The current activity has no supported Sonos volume target.'
      } else {
        details = explicitIdentity
          ? `Request Apple Music track ${candidate.provider_id} at volume ${target} (${mode})? HomeHub will verify approval and current authority before it plays. No volume change or queue clearing.`
          : `Start ${candidate.title} on Sonos at volume ${target} (${mode})? HomeHub will not change volume or clear the queue.`
        confirming = true
      }
    } catch {
      guardMessage = 'Could not verify HomeHub and Sonos. No playback request was sent.'
    } finally {
      checking = false
    }
  }

  async function play() {
    if (!confirming || !eligible || kiosk !== true || checking || sending || eventId) return
    confirming = false
    sending = true
    const id = newEventId()
    if (!reserveAttempt(identity, id)) {
      const prior = getAttempt(identity)
      eventId = prior?.clientEventId || null
      uncertain = true
      sending = false
      return
    }
    eventId = id
    try {
      result = await apiPost('/api/music/assisted-playback', {
        client_event_id: eventId,
        provider: candidate.provider,
        provider_id: candidate.provider_id,
      }, { timeout: 45000 })
      completeAttempt(identity, eventId, result?.status || 'unknown', result?.reason || null)
      if (!result?.status) uncertain = true
    } catch {
      // A failed response is ambiguous: the server might have appended/played.
      // Keep this event consumed, do not generate an ID and silently retry.
      uncertain = true
      completeAttempt(identity, eventId, 'unknown')
    } finally {
      sending = false
    }
  }

  function anotherAttempt() {
    if (!identity || !beginAnotherAttempt(identity)) return
    eventId = null
    result = null
    uncertain = false
    guardMessage = ''
    confirming = false
  }
</script>

{#if eligible}
  <div class="assisted-play-action">
    {#if kiosk === null}
      <small>Checking playback control access…</small>
    {:else if kiosk === false}
      <small>Explicit playback is available only on the Latitude kiosk. Other browsers need strict authentication.</small>
    {:else if eventId}
      {#if sending}
        <small role="status">Verifying playback… Please don't send another request.</small>
      {:else if uncertain}
        <small role="alert">Playback outcome unknown. Check Sonos before attempting again; HomeHub will not replay this request.</small>
      {:else if result?.status === 'played'}
        <small role="status">Verified playing: {candidate.title}. HomeHub recorded this request once.</small>
      {:else}
        <small role="status">Playback {result?.status || 'not confirmed'} ({result?.reason || 'unknown reason'}). No automatic retry.</small>
      {/if}
      {#if !sending && !uncertain && result?.status && result.status !== 'pending'}
        <button type="button" on:click={anotherAttempt}>Check before another attempt</button>
      {/if}
    {:else if confirming}
      <p>{details}</p>
      <div class="assisted-actions">
        <button type="button" on:click={play} disabled={!eligible}>Start approved track</button>
        <button type="button" on:click={() => (confirming = false)}>Cancel</button>
      </div>
    {:else}
      <button type="button" on:click={prepare} disabled={checking}>
        {checking ? 'Checking Sonos…' : 'Play approved track'}
      </button>
      {#if guardMessage}<small role="status">{guardMessage}</small>{/if}
    {/if}
  </div>
{/if}

<style>
  .assisted-play-action {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .assisted-play-action small { color: var(--text-muted); font-size: 11px; }
  .assisted-play-action p { margin: 0; color: var(--text-primary); font-size: 12px; }
  .assisted-actions { display: flex; gap: 8px; flex-wrap: wrap; }
  button {
    padding: 7px 11px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    cursor: pointer;
    font-size: 12px;
  }
  button:disabled { opacity: .6; cursor: not-allowed; }
  .assisted-actions button:first-child { border-color: var(--accent); color: var(--accent); }
</style>
