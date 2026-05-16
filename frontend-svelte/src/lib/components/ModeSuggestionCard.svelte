<script>
  import { modeSuggestion, dismissModeSuggestion } from '$lib/stores/modeSuggestion.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import { addError } from '$lib/stores/errors.js'

  // Direct fetch (not apiPost) so we can swallow 410 Gone silently —
  // that's the "suggestion auto-expired or was superseded between WS
  // broadcast and click" case and shouldn't surface an error toast.
  /** @param {string} path */
  async function postSilently(path) {
    try {
      const res = await fetch(path, { method: 'POST' })
      if (res.status === 410) return  // expected race; dismiss silently
      if (!res.ok) addError(`POST ${path}: ${res.status}`)
    } catch (e) {
      addError(`POST ${path}: network error`)
    }
  }

  async function accept() {
    if (!$modeSuggestion) return
    dismissModeSuggestion()  // optimistic — WS confirmation backs us up
    await postSilently('/api/rules/suggestion/accept')
  }

  async function dismiss() {
    if (!$modeSuggestion) return
    dismissModeSuggestion()
    await postSilently('/api/rules/suggestion/dismiss')
  }
</script>

{#if $modeSuggestion}
  {@const color = modeColor($modeSuggestion.predicted_mode)}
  {@const label = modeLabel($modeSuggestion.predicted_mode)}
  <section class="widget widget-suggestion" style="--accent: {color}">
    <div class="suggestion-body">
      <span class="suggestion-icon" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="10" cy="10" r="8" />
          <path d="M10 6v4l2.5 1.5" />
        </svg>
      </span>
      <div class="suggestion-text">
        <div class="suggestion-headline">
          You're usually in <strong>{label}</strong> mode around this time
        </div>
        <div class="suggestion-meta">
          {$modeSuggestion.confidence}% confidence · {$modeSuggestion.sample_count} observations
        </div>
      </div>
    </div>
    <div class="suggestion-actions">
      <button class="suggestion-btn suggestion-btn-accept" on:click={accept} aria-label="Switch mode">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4,10 8,14 16,6" />
        </svg>
        Switch
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
