<script>
  import { apiPost } from '$lib/api.js'
  import { validBrightnessSuggestion, validModeSuggestion } from '$lib/quietAtlas/suggestionValidation.js'
  import { brightnessAcceptanceFeedback } from '$lib/quietAtlas/brightnessAcceptanceFeedback.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { ambientContext } from '$lib/quietAtlas/ambient.js'
  import { modeSuggestion, dismissModeSuggestion } from '$lib/stores/modeSuggestion.js'
  import { brightnessSuggestion, dismissBrightnessSuggestion } from '$lib/stores/brightnessSuggestion.js'
  import { musicSuggestion, musicAutoPlayed, dismissMusicSuggestion } from '$lib/stores/music.js'
  import { playFavorite } from '$lib/stores/init.js'

  const MODES = { working:'Working', gaming:'Gaming', watching:'Watching', cooking:'Cooking', relax:'Relax', social:'Party' }
  let pending = false
  let feedback = ''
  /** @type {Set<number>} */
  let attemptedBrightness = new Set()
  /** @type {Set<number>} */
  let attemptedModes = new Set()
  /** @type {Array<{id:number,message:string,complete:boolean}>} */
  let brightnessReceipts = []

  /** @param {number} id @param {string} message @param {boolean} complete */
  function recordReceipt(id, message, complete) {
    const next = {id,message,complete}
    brightnessReceipts = brightnessReceipts.some(row=>row.id === id)
      ? brightnessReceipts.map(row=>row.id === id ? next : row)
      : [...brightnessReceipts,next]
  }
  // Require house-state evidence received on the current connection.
  $: available = $connected && ['home','winding_down'].includes($ambientContext?.house_state ?? '')
  $: mode = available && $modeSuggestion && validModeSuggestion($modeSuggestion) ? $modeSuggestion : null
  $: brightness = available && $brightnessSuggestion && validBrightnessSuggestion($brightnessSuggestion) ? $brightnessSuggestion : null
  $: canAcceptBrightness = available && $deviceStatus.hue === true && $deviceStatus.light_command_results === true
  $: music = available && $deviceStatus.sonos && $musicSuggestion && typeof $musicSuggestion.title === 'string' && $musicSuggestion.title.trim() ? $musicSuggestion : null

  /** @param {'accept'|'dismiss'} action @param {number} id */
  async function resolveMode(action, id) {
    if (!available || pending || !Number.isSafeInteger(id) || id <= 0 || attemptedModes.has(id) || mode?.suggestion_id !== id) return
    const intended = mode
    attemptedModes = new Set([...attemptedModes,id])
    pending = true
    feedback = 'Sending suggestion response…'
    try {
      const result = await apiPost('/api/rules/suggestion/' + action + '/' + id)
      if (result?.status === 'ok' && (action === 'dismiss' || result.applied_mode === intended.predicted_mode)) {
        feedback = action === 'dismiss' ? 'Dismissal acknowledged.' : 'Suggestion acknowledged. Check HomeHub’s reported state.'
      } else feedback = 'Suggestion response unconfirmed. Check HomeHub before another action.'
    } catch {
      feedback = 'Suggestion response unconfirmed or expired. Check HomeHub before another action.'
    } finally {
      // An uncertain request must not leave the same card ready for retry.
      if ($modeSuggestion === intended) dismissModeSuggestion()
      pending = false
    }
  }
  /** @param {'accept'|'dismiss'} action @param {number} id */
  async function resolveBrightness(action, id) {
    if (!available || pending || !Number.isSafeInteger(id) || id <= 0 || attemptedBrightness.has(id) || brightness?.id !== id) return
    if (action === 'accept' && !canAcceptBrightness) return
    const intended = brightness
    attemptedBrightness = new Set([...attemptedBrightness,id])
    pending = true
    recordReceipt(id, action === 'accept' ? 'Saving brightness preference…' : 'Dismissing suggestion…', false)
    try {
      const result = await apiPost('/api/rules/brightness-suggestion/' + action + '/' + id, undefined, {timeout:20000})
      const message = action === 'accept' ? brightnessAcceptanceFeedback(result).message
        : result?.status === 'ok' ? 'Dismissal acknowledged.' : 'Dismissal unconfirmed.'
      recordReceipt(id,message,true)
    } catch (error) {
      recordReceipt(id, /failed: 410\b/.test(error instanceof Error ? error.message : String(error))
        ? 'Suggestion no longer pending. No retry sent.'
        : action === 'accept' ? 'Brightness acceptance unconfirmed. Check saved preferences and actual lights before another action.' : 'Dismissal unconfirmed. No retry sent.', true)
    } finally {
      if ($brightnessSuggestion === intended) dismissBrightnessSuggestion()
      pending = false
    }
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
    finally { if ($musicSuggestion === intended) dismissMusicSuggestion(); pending = false }
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

{#if mode || brightness || music || ($connected && $musicAutoPlayed) || feedback || brightnessReceipts.length}
  <section class="suggestions" aria-label="HomeHub suggestions" aria-busy={pending}>
    {#if mode}
      <article>
        <div><span class="eyebrow">MODE SUGGESTION</span><strong>Switch to {MODES[mode.predicted_mode]}?</strong><p>{mode.confidence}% reported confidence · {mode.sample_count} observations</p></div>
        <div class="actions"><button type="button" disabled={pending || attemptedModes.has(mode.suggestion_id)} on:click={() => resolveMode('dismiss',mode.suggestion_id)}>Dismiss</button><button class="primary" type="button" disabled={pending || attemptedModes.has(mode.suggestion_id)} on:click={() => resolveMode('accept',mode.suggestion_id)}>Switch</button></div>
      </article>
    {/if}
    {#if brightness}
      <article>
        <div><span class="eyebrow">LEARNED LIGHTING</span><strong>{brightnessLabel(brightness.payload)}</strong><p>{brightness.payload.mode} · {brightness.payload.period} · {brightness.payload.weather_class}. Save preference and request an immediate adjustment? Existing lighting protections apply.</p>{#if !canAcceptBrightness}<p>Acceptance unavailable until guarded lighting is connected.</p>{/if}</div>
        <div class="actions"><button type="button" disabled={pending || attemptedBrightness.has(brightness.id)} on:click={() => resolveBrightness('dismiss',brightness.id)}>Dismiss</button><button type="button" class="primary" disabled={pending || !canAcceptBrightness || attemptedBrightness.has(brightness.id)} on:click={() => resolveBrightness('accept',brightness.id)}>Save preference</button></div>
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
    {#each brightnessReceipts as receipt (receipt.id)}
      <article class="feedback" role="status" aria-live="polite" aria-label={'Brightness suggestion #' + receipt.id}>
        <div><strong>Suggestion #{receipt.id}</strong><p>{receipt.message}</p></div>
        {#if receipt.complete}<button type="button" aria-label={'Close suggestion #' + receipt.id + ' result'} on:click={() => brightnessReceipts = brightnessReceipts.filter(row=>row.id !== receipt.id)}>Close</button>{/if}
      </article>
    {/each}
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
