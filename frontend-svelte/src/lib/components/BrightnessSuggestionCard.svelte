<script>
  import { brightnessSuggestion, dismissBrightnessSuggestion } from '$lib/stores/brightnessSuggestion.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import { addError } from '$lib/stores/errors.js'

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
    if (!$brightnessSuggestion) return
    const id = $brightnessSuggestion.id
    dismissBrightnessSuggestion()
    await postSilently(`/api/rules/brightness-suggestion/accept/${id}`)
  }

  async function dismiss() {
    if (!$brightnessSuggestion) return
    const id = $brightnessSuggestion.id
    dismissBrightnessSuggestion()
    await postSilently(`/api/rules/brightness-suggestion/dismiss/${id}`)
  }

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
          During <strong>{weatherLabel(payload.weather_class)}</strong> {lbl} you've set
          <strong>L{payload.light_id}</strong> to
          <strong>~{Math.round((payload.suggested_bri / 254) * 100)}%</strong>
          {#if payload.base_bri}
            (default is {Math.round((payload.base_bri / 254) * 100)}%)
          {/if}
        </div>
        <div class="suggestion-meta">
          {payload.sample_count} observation{payload.sample_count === 1 ? '' : 's'} · apply automatically next time?
        </div>
      </div>
    </div>
    <div class="suggestion-actions">
      <button class="suggestion-btn suggestion-btn-accept" on:click={accept} aria-label="Apply automatically">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4,10 8,14 16,6" />
        </svg>
        Apply
      </button>
      <button class="suggestion-btn suggestion-btn-dismiss" on:click={dismiss} aria-label="Dismiss suggestion">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="5" x2="15" y2="15" />
          <line x1="15" y1="5" x2="5" y2="15" />
        </svg>
      </button>
    </div>
  </section>
{/if}

<style>
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
