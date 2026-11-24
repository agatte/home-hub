<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { brightnessAcceptanceFeedback } from '$lib/quietAtlas/brightnessAcceptanceFeedback.js'
  import { brightnessSuggestion, showBrightnessSuggestion, dismissBrightnessSuggestion } from '$lib/stores/brightnessSuggestion.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import { addError } from '$lib/stores/errors.js'

  let pending = false
  /** @type {Array<{id:number,message:string,complete:boolean}>} */
  let receipts = []
  /** @type {Set<number>} */
  let attempted = new Set()

  /** @param {number} id @param {string} message @param {boolean} complete */
  function recordReceipt(id, message, complete) {
    const next = {id, message, complete}
    receipts = receipts.some(row => row.id === id)
      ? receipts.map(row => row.id === id ? next : row)
      : [...receipts, next]
  }

  /** @param {string} path */
  async function postSilently(path) {
    try {
      const res = await fetch(path, { method: 'POST' })
      if (res.status === 410) return // expected race; dismiss silently
      if (!res.ok) addError(`POST ${path}: ${res.status}`)
    } catch (e) {
      addError(`POST ${path}: network error`)
    }
  }

  async function accept() {
    if (!$brightnessSuggestion || pending) return
    const id = $brightnessSuggestion.id
    if (!Number.isSafeInteger(id) || id <= 0 || attempted.has(id)) return
    attempted = new Set([...attempted, id])
    pending = true
    recordReceipt(id, 'Saving brightness preference…', false)
    dismissBrightnessSuggestion()
    try {
      const result = await apiPost(`/api/rules/brightness-suggestion/accept/${id}`, undefined, { timeout: 20000 })
      const outcome = brightnessAcceptanceFeedback(result)
      recordReceipt(id, outcome.message, true)
      if (outcome.incomplete) addError('Brightness suggestion #' + id + ': ' + outcome.message)
    } catch (error) {
      recordReceipt(id, /failed: 410\b/.test(error instanceof Error ? error.message : String(error))
        ? 'Suggestion no longer pending. No retry sent.'
        : 'Brightness acceptance unconfirmed. Check saved preferences and actual lights before another action.', true)
    } finally {
      pending = false
    }
  }

  async function dismiss() {
    if (!$brightnessSuggestion || pending) return
    const id = $brightnessSuggestion.id
    if (!Number.isSafeInteger(id) || id <= 0) return
    pending = true
    dismissBrightnessSuggestion()
    try { await postSilently(`/api/rules/brightness-suggestion/dismiss/${id}`) }
    finally { pending = false }
  }


  onMount(async () => {
    if ($brightnessSuggestion) return
    try {
      const res = await apiGet('/api/rules/suggestions?status=pending&limit=20')
      const pending = (res?.suggestions || []).find((row) => row.kind === 'brightness' && row.payload)
      if (pending) showBrightnessSuggestion(pending)
    } catch {
      // apiGet already reports the error; leave the card hidden.
    }
  })

  function weatherLabel(cls) {
    return ({
      thunderstorm: 'thunderstorm',
      rain: 'rainy',
      clouds: 'overcast',
      snow: 'snowy',
      golden_hour: 'golden-hour',
      clear: 'clear',
    })[cls] || cls
  }

  function roomLabel(room) {
    return ({
      bedroom: 'Bedroom',
      kitchen: 'Kitchen',
      living_room: 'Living room',
    })[room] || room
  }

  function pctFromBri(bri) {
    return Math.round((Number(bri || 0) / 254) * 100)
  }

  function evidenceText(payload) {
    const n = Number(payload.sample_count || 0)
    const days = Number(payload.distinct_days || 0)
    if (days > 0) return `${n} observation${n === 1 ? '' : 's'} across ${days} day${days === 1 ? '' : 's'}`
    return `${n} observation${n === 1 ? '' : 's'}`
  }
</script>

{#if $brightnessSuggestion}
  {@const payload = $brightnessSuggestion.payload || {}}
  {@const color = modeColor(payload.mode || 'idle')}
  {@const lbl = modeLabel(payload.mode || 'idle')}
  <section class="widget widget-suggestion" style="--accent: {color}">
    <div class="suggestion-body">
      <span class="suggestion-icon" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="10" cy="10" r="4" />
          <path d="M10 1.5v2.5M10 16v2.5M1.5 10h2.5M16 10h2.5M3.5 3.5l1.8 1.8M14.7 14.7l1.8 1.8M3.5 16.5l1.8-1.8M14.7 5.3l1.8-1.8" />
        </svg>
      </span>
      <div class="suggestion-text">
        <div class="suggestion-headline">
          {#if payload.scope === 'room'}
            During <strong>{weatherLabel(payload.weather_class)}</strong> {lbl},
            <strong>{roomLabel(payload.room)}</strong> has been landing around
            <strong>~{payload.target_pct ?? pctFromBri(payload.suggested_bri)}%</strong>
          {:else}
            During <strong>{weatherLabel(payload.weather_class)}</strong> {lbl} you've set
            <strong>L{payload.light_id}</strong> to
            <strong>~{pctFromBri(payload.suggested_bri)}%</strong>
            {#if payload.base_bri}
              (default is {pctFromBri(payload.base_bri)}%)
            {/if}
          {/if}
        </div>
        <div class="suggestion-meta">
          {payload.sample_count} observation{payload.sample_count === 1 ? '' : 's'} · save preference and request an immediate adjustment? Existing lighting protections apply.
        </div>
      </div>
    </div>
    <div class="suggestion-actions">
      <button class="suggestion-btn suggestion-btn-accept" on:click={accept} disabled={pending || attempted.has($brightnessSuggestion.id)} aria-label="Apply automatically">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4,10 8,14 16,6" />
        </svg>
        Apply
      </button>
      <button class="suggestion-btn suggestion-btn-dismiss" on:click={dismiss} disabled={pending} aria-label="Dismiss suggestion">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="5" x2="15" y2="15" />
          <line x1="15" y1="5" x2="5" y2="15" />
        </svg>
      </button>
    </div>
  </section>
{/if}
{#each receipts as receipt (receipt.id)}
  <div class="brightness-feedback" role="status" aria-live="polite" aria-label={'Brightness suggestion #' + receipt.id}>
    <span>Suggestion #{receipt.id}: {receipt.message}</span>
    {#if receipt.complete}<button type="button" class="suggestion-btn" aria-label={'Close suggestion #' + receipt.id + ' result'} on:click={() => receipts = receipts.filter(row => row.id !== receipt.id)}>Close</button>{/if}
  </div>
{/each}

<style>
  .brightness-feedback {display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:12px 16px;color:var(--text-primary);font-size:13px;line-height:1.5;}
  .suggestion-btn:disabled {opacity:.55;cursor:not-allowed;}
  .widget-suggestion {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 20px;
    border-left: 3px solid var(--accent);
  }

  .suggestion-body {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
    flex: 1;
  }

  .suggestion-icon {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--accent) 18%, transparent);
    color: var(--accent);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .suggestion-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .suggestion-headline {
    font-size: 14px;
    color: var(--text-primary, #fff);
    line-height: 1.35;
  }

  .suggestion-headline strong {
    color: var(--accent);
    font-weight: 600;
  }

  .suggestion-meta {
    font-size: 12px;
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
  }

  .suggestion-actions {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
  }

  .suggestion-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.12);
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-primary, #fff);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.18s, background 0.18s, color 0.18s;
  }

  .suggestion-btn:hover {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
  }

  .suggestion-btn-accept {
    border-color: color-mix(in srgb, var(--accent) 60%, transparent);
    background: color-mix(in srgb, var(--accent) 22%, transparent);
    color: var(--accent);
  }

  .suggestion-btn-accept:hover {
    background: color-mix(in srgb, var(--accent) 32%, transparent);
  }

  .suggestion-btn-dismiss {
    padding: 8px 10px;
  }

  @media (max-width: 600px) {
    .widget-suggestion {
      flex-direction: column;
      align-items: stretch;
      gap: 12px;
    }
    .suggestion-actions {
      justify-content: flex-end;
    }
  }
</style>
