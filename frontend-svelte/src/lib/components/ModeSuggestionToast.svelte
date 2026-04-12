<script>
  import { modeSuggestion, dismissModeSuggestion } from '$lib/stores/modeSuggestion.js'
  import { apiPost } from '$lib/api.js'
  import { modeColor, modeLabel } from '$lib/theme.js'

  async function accept() {
    if (!$modeSuggestion) return
    try {
      await apiPost('/api/rules/suggestion/accept')
    } catch {
      /* ignore */
    }
    dismissModeSuggestion()
  }

  async function dismiss() {
    try {
      await apiPost('/api/rules/suggestion/dismiss')
    } catch {
      /* ignore */
    }
    dismissModeSuggestion()
  }
</script>

{#if $modeSuggestion}
  {@const color = modeColor($modeSuggestion.predicted_mode)}
  {@const label = modeLabel($modeSuggestion.predicted_mode)}
  <div class="music-toast music-toast-suggestion" style="--accent: {color}">
    <div class="music-toast-content">
      <span class="music-toast-icon">
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="10" cy="10" r="8" />
          <path d="M10 6v4l2.5 1.5" />
        </svg>
      </span>
      <span class="music-toast-text">
        Switch to <strong>{label}</strong>? <span style="opacity: 0.7">{$modeSuggestion.confidence}% confidence</span>
      </span>
    </div>
    <div class="music-toast-actions">
      <button class="music-toast-btn music-toast-accept" on:click={accept}>
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4,10 8,14 16,6" />
        </svg>
        Switch
      </button>
      <button class="music-toast-btn music-toast-dismiss" on:click={dismiss}>
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="5" x2="15" y2="15" />
          <line x1="15" y1="5" x2="5" y2="15" />
        </svg>
      </button>
    </div>
    <div class="music-toast-progress" style="animation-duration: 20s"></div>
  </div>
{/if}
