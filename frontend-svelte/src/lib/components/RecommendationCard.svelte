<script>
  /** @type {any} */
  export let rec
  /** @type {(id: number, action: 'liked' | 'dismissed') => void} */
  export let onFeedback = () => {}
  /** @type {(previewUrl: string) => Promise<void>} */
  export let onPreview = async () => {}

  let previewing = false

  async function handlePreview() {
    if (!rec.preview_url) return
    previewing = true
    await onPreview(rec.preview_url)
    setTimeout(() => { previewing = false }, 3000)
  }
</script>

<div class="rec-card">
  {#if rec.artwork_url}
    <img class="rec-artwork" src={rec.artwork_url} alt={rec.artist_name} loading="lazy" />
  {:else}
    <div class="rec-artwork rec-artwork-placeholder">
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M8 17.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5Z" />
        <path d="M10.5 15V3.5L17 2v11" />
      </svg>
    </div>
  {/if}
  <div class="rec-info">
    <span class="rec-artist">{rec.artist_name}</span>
    {#if rec.track_name}
      <span class="rec-track">{rec.track_name}</span>
    {/if}
    {#if rec.reason}
      <span class="rec-reason">{rec.reason}</span>
    {/if}
  </div>
  <div class="rec-actions">
    {#if rec.preview_url}
      <button class="rec-action-btn rec-preview-btn" on:click={handlePreview} disabled={previewing} title="Play 30s preview on Sonos">
        <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" stroke="none">
          <polygon points="6,4 18,10 6,16" />
        </svg>
      </button>
    {/if}
    <button class="rec-action-btn rec-like-btn" on:click={() => onFeedback(rec.id, 'liked')} title="Like">
      <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="4,10 8,14 16,6" />
      </svg>
    </button>
    <button class="rec-action-btn rec-dismiss-btn" on:click={() => onFeedback(rec.id, 'dismissed')} title="Dismiss">
      <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="5" y1="5" x2="15" y2="15" />
        <line x1="15" y1="5" x2="5" y2="15" />
      </svg>
    </button>
    {#if rec.itunes_url}
      <a class="rec-action-btn rec-apple-btn" href={rec.itunes_url} target="_blank" rel="noopener noreferrer" title="Open in Apple Music">
        <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 3l3 3-3 3" />
          <path d="M3 10V8a4 4 0 0 1 4-4h10" />
        </svg>
      </a>
    {/if}
  </div>
</div>
