<script>
  import { musicSuggestion, musicAutoPlayed, dismissMusicSuggestion } from '$lib/stores/music.js'
  import { playFavorite } from '$lib/stores/init.js'

  /** @type {Record<string, string>} */
  const MODE_LABELS = {
    gaming: 'Gaming',
    working: 'Working',
    watching: 'Watching',
    relax: 'Relax',
    social: 'Party',
    movie: 'Movie',
  }

  async function accept() {
    if (!$musicSuggestion) return
    try {
      await playFavorite($musicSuggestion.title)
    } catch {
      /* ignore */
    }
    dismissMusicSuggestion()
  }
</script>

{#if $musicAutoPlayed && !$musicSuggestion}
  <div class="music-toast music-toast-info">
    <span class="music-toast-icon">
      <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
        <path d="M10.5 15V3.5L17 2v11" />
        <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
      </svg>
    </span>
    <span class="music-toast-text">
      Now playing <strong>{$musicAutoPlayed.title}</strong> for {MODE_LABELS[$musicAutoPlayed.mode] || $musicAutoPlayed.mode}
    </span>
  </div>
{:else if $musicSuggestion}
  <div class="music-toast music-toast-suggestion">
    <div class="music-toast-content">
      <span class="music-toast-icon">
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
          <path d="M10.5 15V3.5L17 2v11" />
          <path d="M17 13a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z" />
        </svg>
      </span>
      <span class="music-toast-text">
        {MODE_LABELS[$musicSuggestion.mode] || $musicSuggestion.mode} mode — play <strong>{$musicSuggestion.title}</strong>?
      </span>
    </div>
    <div class="music-toast-actions">
      <button class="music-toast-btn music-toast-accept" on:click={accept}>
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="6,4 18,10 6,16" fill="currentColor" stroke="none" />
        </svg>
        Play
      </button>
      <button class="music-toast-btn music-toast-dismiss" on:click={dismissMusicSuggestion}>
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="5" y1="5" x2="15" y2="15" />
          <line x1="15" y1="5" x2="5" y2="15" />
        </svg>
      </button>
    </div>
    <div class="music-toast-progress"></div>
  </div>
{/if}
