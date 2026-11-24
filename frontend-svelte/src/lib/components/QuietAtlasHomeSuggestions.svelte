<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { automation } from '$lib/stores/automation.js'
  import { modeSuggestion, dismissModeSuggestion } from '$lib/stores/modeSuggestion.js'
  import { brightnessSuggestion, showBrightnessSuggestion, dismissBrightnessSuggestion } from '$lib/stores/brightnessSuggestion.js'
  import { musicSuggestion, musicAutoPlayed, dismissMusicSuggestion } from '$lib/stores/music.js'
  import { playFavorite } from '$lib/stores/init.js'

  const MODES = { working:'Working', gaming:'Gaming', watching:'Watching', cooking:'Cooking', relax:'Relax', social:'Party' }
  let pending = false
  let feedback = ''
  let mounted = false
  let readEpoch = 0
  $: available = $connected && ['home','winding_down'].includes($automation.house_state ?? '')
  $: mode = available && $modeSuggestion && Number.isSafeInteger($modeSuggestion.suggestion_id) && $modeSuggestion.suggestion_id > 0 && MODES[$modeSuggestion.predicted_mode] ? $modeSuggestion : null
  $: brightness = available && $brightnessSuggestion && Number.isSafeInteger($brightnessSuggestion.id) && $brightnessSuggestion.id > 0 && $brightnessSuggestion.payload ? $brightnessSuggestion : null
  $: music = available && $deviceStatus.sonos && $musicSuggestion && typeof $musicSuggestion.title === 'string' && $musicSuggestion.title.trim() ? $musicSuggestion : null

  onMount(() => {
    mounted = true
    return () => { mounted = false; readEpoch += 1 }
  })
  $: if (mounted) {
    if (available) void restoreBrightnessSuggestion()
    else readEpoch += 1
  }
  async function restoreBrightnessSuggestion() {
    const ticket = ++readEpoch
    if ($brightnessSuggestion) return
    try {
      const result = await apiGet('/api/rules/suggestions?status=pending&limit=20')
      if (!mounted || ticket !== readEpoch || !available || $brightnessSuggestion) return
      const row = (Array.isArray(result?.suggestions) ? result.suggestions : []).find(row => row.kind === 'brightness' && row.payload && Number.isSafeInteger(row.id) && row.id > 0)
      if (row) showBrightnessSuggestion(row)
    } catch { /* existing api error surface */ }
  }
  /** @param {'mode'|'brightness'} kind @param {'accept'|'dismiss'} action @param {number} id */
  async function resolve(kind, action, id) {
    if (!available || pending || !Number.isSafeInteger(id) || id <= 0) return
    const current = kind === 'mode' ? mode : brightness
    const currentId = kind === 'mode' ? mode?.suggestion_id : brightness?.id
    if (!current || currentId !== id) return
    pending = true
    feedback = 'Sending suggestion response…'
    try {
      const endpoint = kind === 'mode' ? 'suggestion' : 'brightness-suggestion'
      const result = await apiPost('/api/rules/' + endpoint + '/' + action + '/' + id)
      if (result?.status === 'ok' || (kind === 'brightness' && action === 'accept' && result?.status === 'accepted')) {
        if (kind === 'mode' && $modeSuggestion?.suggestion_id === id) dismissModeSuggestion()
        if (kind === 'brightness' && $brightnessSuggestion?.id === id) dismissBrightnessSuggestion()
        feedback = action === 'dismiss' ? 'Dismissal acknowledged.' : 'Suggestion acknowledged. Check HomeHub’s reported state.'
      } else feedback = 'Suggestion response unconfirmed. Check HomeHub before another action.'
    } catch {
      feedback = 'Suggestion response unconfirmed or expired. Check HomeHub before another action.'
    } finally { pending = false }
  }
  /** @param {string} title */
  async function play(title) {
    if (!available || pending || !$deviceStatus.sonos || !music || music.title !== title) return
    const intended = music
    pending = true
    feedback = 'Requesting playback…'
    try {
      await playFavorite(title)
      if ($musicSuggestion === intended) dismissMusicSuggestion()
      feedback = 'Playback requested. Check Now Playing for the reported result.'
    } catch { feedback = 'Playback unconfirmed. Check your speaker before another action.' }
    finally { pending = false }
  }
  /** @param {unknown} payload */
  function brightnessLabel(payload) {
    if (!payload || typeof payload !== 'object') return 'Brightness preference'
    const p = /** @type {Record<string, any>} */ (payload)
    const pct = Number.isFinite(p.target_pct) ? p.target_pct : Number.isFinite(p.suggested_bri) ? Math.round(p.suggested_bri / 254 * 100) : null
    const target = p.scope === 'room' && typeof p.room === 'string' ? p.room.replaceAll('_',' ') : typeof p.light_id === 'string' ? 'L' + p.light_id : 'Lighting'
    return target + (pct !== null && pct >= 0 && pct <= 100 ? ' · about ' + pct + '%' : '')
  }
</script>

{#if mode || brightness || music || ($connected && $musicAutoPlayed) || feedback}
  <section class="suggestions" aria-label="HomeHub suggestions" aria-busy={pending}>
    {#if mode}
      <article>
        <div><span class="eyebrow">MODE SUGGESTION</span><strong>Switch to {MODES[mode.predicted_mode]}?</strong><p>{mode.confidence}% reported confidence · {mode.sample_count} observations</p></div>
        <div class="actions"><button type="button" disabled={pending} on:click={() => resolve('mode','dismiss',mode.suggestion_id)}>Dismiss</button><button class="primary" type="button" disabled={pending} on:click={() => resolve('mode','accept',mode.suggestion_id)}>Switch</button></div>
      </article>
    {/if}
    {#if brightness}
      <article>
        <div><span class="eyebrow">LEARNED LIGHTING</span><strong>{brightnessLabel(brightness.payload)}</strong><p>{brightness.payload.mode} · {brightness.payload.period} · {brightness.payload.weather_class}. Accepting saves a learned preference and may apply it now.</p></div>
        <div class="actions"><button type="button" disabled={pending} on:click={() => resolve('brightness','dismiss',brightness.id)}>Dismiss</button><button class="primary" type="button" disabled={pending} on:click={() => resolve('brightness','accept',brightness.id)}>Save preference</button></div>
      </article>
    {/if}
    {#if music}
      <article>
        <div><span class="eyebrow">MUSIC SUGGESTION</span><strong>Play {music.title}?</strong></div>
        <div class="actions"><button type="button" disabled={pending} on:click={dismissMusicSuggestion}>Dismiss</button><button class="primary" type="button" disabled={pending} on:click={() => play(music.title)}>Play</button></div>
      </article>
    {:else if $connected && $musicAutoPlayed}
      <article><div><span class="eyebrow">MUSIC AUTOMATION</span><strong>HomeHub reported a playback request for {$musicAutoPlayed.title}</strong><p>Check Now Playing for current speaker status.</p></div></article>
    {/if}
    {#if feedback}<p class="feedback" role="status">{feedback}</p>{/if}
  </section>
{/if}

<style>
  .suggestions {display:grid;gap:9px;margin:0 0 18px;min-width:0;color:var(--hh-ink);}
  article {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;padding:14px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-card);background:var(--hh-card-background);}
  article>div:first-child {flex:1 1 180px;min-width:0;display:grid;gap:4px;overflow-wrap:anywhere;}
  .eyebrow {font-size:10px;letter-spacing:.12em;font-weight:750;color:var(--hh-accent);}
  strong {font-size:15px;}
  p {font-size:12px;line-height:1.5;color:var(--hh-muted);margin:0;}
  .actions {display:flex;flex-wrap:wrap;gap:8px;}
  button {min-height:44px;padding:8px 12px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);background:var(--hh-control);color:var(--hh-ink);font:inherit;font-size:13px;font-weight:650;cursor:pointer;}
  button.primary {background:var(--hh-accent);color:var(--hh-panel-deep);}
  button:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible {outline:3px solid var(--hh-focus);outline-offset:2px;}
  .feedback {padding:8px 12px;}
</style>
