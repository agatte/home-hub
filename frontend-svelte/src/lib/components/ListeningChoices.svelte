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
  let playbackMessage = ''
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
      } else if (receipt?.status === 'suppressed') {
        playbackMessage = `Your ${label} did not start. Find music again when Sonos is ready.`
      } else {
        playbackMessage = 'Playback could not be confirmed. Check Sonos before trying again.'
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
                <details><summary>View mix</summary><ul>{#each choice.tracks || [] as track}<li>{track.title}</li>{/each}</ul></details>
              {/if}
              {#if albumLink(choice)}
                <a class="open" href={albumLink(choice) || undefined} target="_blank" rel="noopener noreferrer">Open in Apple Music <ArrowUpRight size={15}/></a>
              {:else if choice.kind === 'favorite' || choice.kind === 'artist_mix'}
                {#if selection?.choice_ids.includes(choice.id)}
                  <button class="open" type="button" disabled={starting || busy} on:click={() => startSelection(choice)}>Play on Sonos <Headphones size={15}/></button>
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
      <p class="footnote"><Headphones size={15}/> Sonos playback requires an owner session and an available queue. Mixes and supported playlists may include up to three verified similar tracks queued next.</p>
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
