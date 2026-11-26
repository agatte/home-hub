<script>
  import { onDestroy } from 'svelte'
  import { ArrowUpRight, Headphones, Music2, Sparkles, Disc3 } from 'lucide-svelte'
  import { apiPost } from '$lib/api.js'

  const moods = [
    { label: 'Relaxing', request: 'relaxing' },
    { label: 'Upbeat', request: 'upbeat' },
    { label: 'Party', request: 'party' },
    { label: 'Focus', request: 'focus' },
    { label: 'Something new', request: 'new' },
    { label: 'Familiar', request: 'something familiar' },
  ]
  let query = ''
  let requested = ''
  let busy = false
  let error = ''
  /** @type {any | null} */
  let result = null
  /** @type {any | null} */
  let selection = null
  let starting = false
  let selectionUsed = false
  let playbackMessage = ''
  let availabilityMessage = ''
  let alive = true
  onDestroy(() => { alive = false })

  /** @param {string} value */
  async function findMusic(value) {
    const text = value.trim()
    if (busy || starting || !text) return
    query = text
    requested = text
    busy = true
    error = ''
    result = null
    selection = null
    playbackMessage = ''
    selectionUsed = false
    availabilityMessage = ''
    try {
      const response = await apiPost('/api/music/request/preview', {
        request: text, listening: true, count: 6, tracks_per_artist: 3,
      }, { timeout: 30000 })
      if (!alive) return
      const listening = response?.listening
      if (!listening || listening.actuation_allowed !== false || !Array.isArray(listening.choices)) {
        error = 'Listening choices are unavailable. Try again later.'
        return
      }
      result = listening
      const ticket = response?.listening_selection
      if (ticket?.status === 'selection_available' && ticket.actuation_allowed === false
          && typeof ticket.token === 'string' && Array.isArray(ticket.choice_ids)) {
        selection = ticket
      } else {
        availabilityMessage = ({
          owner_context_required: 'Play on Sonos requires a direct owner session.',
          no_eligible_playback: 'No verified playable choices are available for this mood.',
          mode_changed: 'The house mode changed. Find music again.',
          service_unavailable: 'The listening service is unavailable right now.',
          preview_unavailable: 'The music preview is unavailable right now.',
        })[ticket?.reason] || 'Sonos playback is unavailable right now.'
      }
    } catch {
      if (alive) error = 'Could not find music right now. Try again in a moment.'
    } finally {
      if (alive) busy = false
    }
  }

  /** @param {any} choice */
  async function startSelection(choice) {
    if (busy || starting || !selection?.choice_ids.includes(choice.id)) return
    const label = choice.kind === 'favorite' ? 'playlist' : 'mix'
    const token = selection.token
    selection = null
    selectionUsed = true
    starting = true
    playbackMessage = `Starting your ${label} on Sonos...`
    try {
      const receipt = await apiPost('/api/music/listening/start', {
        token, choice_id: choice.id,
      }, { timeout: 120000 })
      if (!alive) return
      if (receipt?.status === 'started') {
        playbackMessage = `Your ${label} started on Sonos.`
        if (Number.isInteger(receipt.continuation_tracks) && receipt.continuation_tracks > 0) {
          playbackMessage += ` ${receipt.continuation_tracks} similar tracks queued next.`
        }
        if (receipt.sustained_listening === true) {
          playbackMessage += ' Continuous listening was enabled for this session.'
        }
      } else if (receipt?.status === 'suppressed') {
        const reason = receipt.reason
        if (['selection_expired', 'selection_mode_changed', 'selection_unavailable', 'choice_not_visible'].includes(reason)) {
          playbackMessage = 'Your selection expired or changed. Find music again.'
        } else if (['mix_member_not_verified', 'current_taste_or_approval_veto', 'favorite_identity_changed'].includes(reason)) {
          playbackMessage = 'This selection is no longer eligible for playback. Find music again.'
        } else {
          playbackMessage = ({
            sonos_busy: 'Sonos already has an active or retained source. HomeHub did not replace it.',
            sonos_queue_changed: 'The Sonos queue changed. HomeHub left it untouched.',
            sonos_queue_owned: 'The existing Sonos queue belongs to another session.',
            sonos_muted: 'Sonos is muted. HomeHub left mute unchanged.',
            manual_source_unavailable: 'The speaker source is unsupported or could not be verified.',
            manual_selection_unavailable: 'This music selection could not be verified.',
            manual_queue_changed: 'The queue or source changed before playback.',
            manual_queue_capacity: 'The existing queue is too large for a verified new selection. HomeHub did not clear it.',
            manual_playlist_unverified: 'The saved playlist contents could not be verified.',
            manual_volume_unavailable: 'The permitted start volume could not be verified.',
            volume_source_changed: 'The speaker changed before volume could be adjusted.',
            volume_evidence_unavailable: 'The speaker state could not be verified for volume adjustment.',
            travel_mode_active: 'HomeHub is in travel mode.',
            returning_home_active: 'HomeHub is still returning home.',
            apartment_away: 'HomeHub is in Away.',
            house_authority_unavailable: 'The current occupancy state could not be verified.',
            tts_active: 'A spoken announcement is using Sonos.',
            ambient_playback_owned: 'An ambient audio operation is using Sonos.',
            sonos_volume_zero: 'Sonos volume is zero. HomeHub left it unchanged.',
            sonos_volume_above_policy: 'The permitted start volume changed before playback.',
            volume_cap_source_changed: 'The speaker or queue changed before volume could be adjusted.',
            volume_cap_evidence_changed: 'The speaker changed before volume could be adjusted.',
            volume_cap_evidence_unavailable: 'The speaker state could not be verified for volume adjustment.',
            volume_cap_authority_changed: 'Another audio action took priority before volume could be adjusted.',
            volume_cap_selection_changed: 'The music selection changed before volume could be adjusted.',
            volume_cap_unavailable: 'Automatic start-volume adjustment is unavailable.',
            volume_or_authority_unavailable: 'The allowed start volume or playback authority could not be verified.',
            audio_ownership_busy: 'Another audio operation owns Sonos right now.',
            authority_changed: 'Another audio action or house-state change took priority.',
            runtime_policy_refused: 'The current house or audio policy does not allow music to start.',
            sonos_unavailable: 'Sonos is not available right now.',
            queue_context_unavailable: 'The Sonos queue could not be verified.',
            sonos_play_mode_owned: 'The speaker is using a different playback mode.',
          })[reason] || `Your ${label} did not start. HomeHub could not verify the playback conditions.`
          playbackMessage += ' Find music again when ready.'
        }
      } else {
        playbackMessage = ({
          volume_cap_unverified: 'The volume adjustment could not be confirmed. HomeHub did not proceed to playback.',
          volume_cap_outcome_unknown: 'The volume adjustment could not be confirmed. HomeHub did not proceed to playback.',
          volume_unverified: 'The volume adjustment could not be confirmed. HomeHub did not proceed to playback.',
          manual_append_unverified: 'The new queue entries could not be verified.',
          manual_stop_unverified: 'The previous source could not be stopped safely.',
          manual_play_mode_unverified: 'The new playback order could not be verified.',
          manual_queue_changed_before_play: 'The queue or source changed during playback setup.',
          manual_play_unverified: 'Sonos did not confirm the new playback command.',
          playback_start_unverified: 'Sonos did not confirm advancing playback.',
        })[receipt?.reason] || 'Playback could not be confirmed.'
        playbackMessage += ' Check Sonos before trying again.'
      }
    } catch {
      if (alive) playbackMessage = 'Playback could not be confirmed. Check Sonos before trying again.'
    } finally {
      if (alive) starting = false
    }
  }

  /** @param {any} choice */
  function albumLink(choice) {
    if (choice.kind !== 'album' || typeof choice.apple_music_url !== 'string') return null
    try {
      const url = new URL(choice.apple_music_url)
      const id = String(choice.id || '').match(/^itunes_album:([0-9]+)$/)?.[1]
      if (!id || url.protocol !== 'https:' || !['music.apple.com', 'itunes.apple.com'].includes(url.host) || url.username || url.password || url.search || url.hash) return null
      return new RegExp('^/[a-z]{2}/album/(?:[^/]+/)?(?:id)?' + id + '$').test(url.pathname) ? url.href : null
    } catch {
      return null
    }
  }

  /** @param {any} choice */
  function subtitle(choice) {
    if (choice.kind === 'favorite') return 'Sonos favorite'
    if (choice.kind === 'album') return 'Album · ' + (choice.artist || 'Apple Music')
    return 'Artist mix · ' + (choice.tracks?.length || 0) + ' tracks'
  }
</script>

<section class="listen" aria-labelledby="listen-title">
  <div class="listen-intro">
    <span class="eyebrow"><Sparkles size={15} /> YOUR MUSIC, YOUR MOMENT</span>
    <h2 id="listen-title">What are you in the mood for?</h2>
    <p>Find something you know, or discover something you might love.</p>
  </div>
  <form on:submit|preventDefault={() => findMusic(query)}>
    <label class="visually-hidden" for="listening-mood">Describe your mood</label>
    <input id="listening-mood" bind:value={query} maxlength="160" placeholder="Relaxing, upbeat, something new..." disabled={busy || starting} autocomplete="off" />
    <button class="find" type="submit" disabled={busy || starting || !query.trim()}>Find music <ArrowUpRight size={17}/></button>
  </form>
  <div class="moods" aria-label="Suggested moods">
    {#each moods as mood}
      <button type="button" class:chosen={requested === mood.request} disabled={busy || starting} on:click={() => findMusic(mood.request)}>{mood.label}</button>
    {/each}
  </div>
  {#if busy}
    <p class="status" role="status">Finding music for “{requested}”…</p>
  {:else if error}
    <p class="status" role="alert">{error}</p>
  {:else if result}
    {#if availabilityMessage}<p class="status" role="status">{availabilityMessage}</p>{/if}
    <div class="results-heading">
      <h3>For your mood</h3>
      <span>{result.choices.length} choices</span>
    </div>
    {#if result.choices.length === 0}
      <p class="status" role="status">No suitable choices yet. Try a different mood.</p>
    {:else}
      {#if result.status === 'partial'}<p class="status" role="status">Showing the choices HomeHub could identify.</p>{/if}
      <div class="choices">
        {#each result.choices as choice (choice.id)}
          <article class="choice">
            <div class="cover" class:album={choice.kind === 'album'} class:mix={choice.kind === 'artist_mix'} aria-hidden="true">
              {#if choice.kind === 'album'}<Disc3 size={36} strokeWidth={1.2}/>{:else if choice.kind === 'artist_mix'}<Sparkles size={36} strokeWidth={1.2}/>{:else}<Music2 size={36} strokeWidth={1.2}/>{/if}
            </div>
            <div class="choice-copy">
              <span class="type">{subtitle(choice)}</span>
              <h4>{choice.title}</h4>
              {#if choice.familiarity === 'familiar' || choice.familiarity === 'proven'}<span class="taste">{choice.kind === 'favorite' ? 'Familiar to you' : 'Familiar artist'}</span>{:else if choice.familiarity === 'exploratory'}<span class="taste">Explore this artist</span>{/if}
              {#if choice.kind === 'album' && choice.matched_track}<p>Suggested from {choice.matched_track}</p>{/if}
              {#if choice.kind === 'artist_mix'}
                <details><summary>View mix</summary><ul>{#each choice.tracks || [] as track}<li>{track.title}{#if track.artist} ? {track.artist}{/if}</li>{/each}</ul></details>
              {/if}
              {#if albumLink(choice)}
                <a class="open" href={albumLink(choice) || undefined} target="_blank" rel="noopener noreferrer">Open album in Apple Music (external) <ArrowUpRight size={15}/></a>
              {:else if choice.kind === 'favorite' || choice.kind === 'artist_mix'}
                {#if selection?.choice_ids.includes(choice.id)}
                  <button class="open" type="button" disabled={starting || busy} on:click={() => startSelection(choice)}>Play on Sonos <Headphones size={15}/></button>
                {:else if selectionUsed}
                  <span class="pending">{starting ? 'Starting selection?' : 'Selection used. Find music for a new selection.'}</span>
                {:else}
                  <span class="pending">{choice.kind === 'favorite' ? 'Playlist' : 'Mix'} playback unavailable for this selection</span>
                {/if}
              {:else}
                <span class="pending">Apple Music destination unavailable</span>
              {/if}
            </div>
          </article>
        {/each}
      </div>
      {#if playbackMessage}<p class="status" role="status">{playbackMessage}</p>{/if}
      <p class="footnote"><Headphones size={15}/> Sonos playback requires an owner session and an available queue. Mixes and supported playlists may include up to three verified similar tracks queued next. HomeHub can replenish a verified playing queue; it never restarts stopped music.</p>
    {/if}
  {/if}
</section>

<style>
  .listen {display:grid;gap:18px;padding:clamp(18px,3vw,32px);border:1px solid var(--hh-line);border-radius:var(--hh-radius-panel);background:linear-gradient(140deg,var(--hh-card-background),var(--hh-panel-deep));min-width:0;}
  .listen-intro {display:grid;gap:8px;}
  .eyebrow {display:flex;align-items:center;gap:7px;color:var(--hh-accent);font-size:10px;font-weight:700;letter-spacing:.12em;}
  h2 {font:500 clamp(26px,4vw,42px)/1.12 var(--hh-display);letter-spacing:-.035em;margin:0;color:var(--hh-ink);}
  p {margin:0;color:var(--hh-muted);font-size:13px;line-height:1.55;}
  form {display:flex;gap:8px;flex-wrap:wrap;}
  input {flex:1 1 180px;min-width:0;min-height:48px;padding:10px 14px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);background:var(--hh-control);color:var(--hh-ink);font:inherit;}
  button,.open {min-height:44px;display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:var(--hh-radius-control);font:inherit;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;}
  .find,.open {background:var(--hh-accent);color:var(--hh-panel-deep);border:1px solid transparent;padding:8px 14px;}
  .moods {display:flex;gap:8px;flex-wrap:wrap;}
  .moods button {background:var(--hh-control);color:var(--hh-ink);border:1px solid var(--hh-line);border-radius:999px;padding:8px 14px;}
  .moods button.chosen {border-color:var(--hh-accent);color:var(--hh-accent);}
  button:disabled {opacity:.55;cursor:default;}
  button:focus-visible,input:focus-visible,a:focus-visible,summary:focus-visible {outline:3px solid var(--hh-focus);outline-offset:3px;}
  .results-heading {display:flex;align-items:baseline;justify-content:space-between;gap:8px;}
  .results-heading h3 {margin:0;font-size:19px;font-weight:600;}
  .results-heading span,.status,.footnote {color:var(--hh-muted);font-size:12px;}
  .choices {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:12px;}
  .choice {min-width:0;display:grid;grid-template-columns:72px minmax(0,1fr);align-items:start;gap:12px;border:1px solid var(--hh-line);background:var(--hh-control);border-radius:var(--hh-radius-control);padding:12px;}
  .cover {display:grid;place-items:center;aspect-ratio:1;border-radius:12px;background:#425950;color:#e8f1eb;}
  .cover.album {background:#645b83;color:#f2e7ff;}
  .cover.mix {background:#8c6045;color:#fff0d4;}
  .choice-copy {display:grid;gap:6px;min-width:0;overflow-wrap:anywhere;}
  .type,.taste,.pending {font-size:11px;color:var(--hh-muted);}
  .taste {color:var(--hh-accent);}
  h4 {margin:0;font-size:16px;line-height:1.2;font-weight:600;}
  .choice p {font-size:12px;}
  .choice details {font-size:12px;color:var(--hh-muted);}
  .choice summary {cursor:pointer;min-height:44px;display:list-item;padding:10px 0;}
  .choice ul {padding-left:16px;}
  .open {justify-self:start;}
  .footnote {display:flex;align-items:center;gap:7px;}
  .visually-hidden {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
  @media(max-width:600px) {.listen{padding:16px;} .find{flex:1 1 auto;}}
</style>
