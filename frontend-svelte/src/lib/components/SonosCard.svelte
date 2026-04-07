<script>
  import Slider from './Slider.svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { sonosCommand } from '$lib/stores/init.js'

  // Volume slider collision handling — ported verbatim from the React
  // SonosCard. The local volume is authoritative while the user is dragging,
  // and we ignore the 2s Sonos poll updates for ~500ms after the last drag
  // so the slider doesn't snap back to a stale server value.
  let localVolume = 0
  let dragging = false
  /** @type {ReturnType<typeof setTimeout> | null} */
  let debounceTimer = null

  // Sync from store when not actively dragging.
  $: if (!dragging) localVolume = $sonos.volume

  $: isPlaying = $sonos.state === 'PLAYING'

  /** @param {number} vol */
  function onVolumeChange(vol) {
    dragging = true
    localVolume = vol
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      sonosCommand('volume', { volume: vol })
      // Re-enable server sync after a short delay.
      setTimeout(() => { dragging = false }, 500)
    }, 150)
  }

  function onPrevious() { sonosCommand('previous') }
  function onNext() { sonosCommand('next') }
  function onPlayPause() { sonosCommand(isPlaying ? 'pause' : 'play') }
</script>

<div class="sonos-card">
  <div class="now-playing">
    {#if $sonos.art_url}
      <img src={$sonos.art_url} alt="Album art" class="album-art" />
    {:else}
      <div class="album-art album-art-placeholder">
        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 18V5l12-2v13" />
          <circle cx="6" cy="18" r="3" />
          <circle cx="18" cy="16" r="3" />
        </svg>
      </div>
    {/if}
    <div class="track-info">
      <div class="track-name">{$sonos.track || 'Nothing playing'}</div>
      <div class="track-artist">{$sonos.artist || '\u00A0'}</div>
      {#if $sonos.album}
        <div class="track-album">{$sonos.album}</div>
      {/if}
    </div>
  </div>

  <div class="playback-controls">
    <button class="control-btn" on:click={onPrevious} aria-label="Previous">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
        <path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" />
      </svg>
    </button>

    <button class="control-btn control-btn-primary" on:click={onPlayPause} aria-label={isPlaying ? 'Pause' : 'Play'}>
      {#if isPlaying}
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
          <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
        </svg>
      {:else}
        <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
          <path d="M8 5v14l11-7z" />
        </svg>
      {/if}
    </button>

    <button class="control-btn" on:click={onNext} aria-label="Next">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
        <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
      </svg>
    </button>
  </div>

  <div class="volume-control">
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" class="volume-icon">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
    </svg>
    <Slider value={localVolume} min={0} max={100} onChange={onVolumeChange} className="volume-slider" />
  </div>
</div>
