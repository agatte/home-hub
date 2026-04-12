<script>
  import Slider from './Slider.svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { sonosCommand } from '$lib/stores/init.js'

  $: isPlaying = $sonos.state === 'PLAYING'

  /** @param {number} vol */
  function onVolumeChange(vol) {
    sonosCommand('volume', { volume: vol })
  }

  function onPrevious() { sonosCommand('previous') }
  function onNext() { sonosCommand('next') }
  function onPlayPause() { sonosCommand(isPlaying ? 'pause' : 'play') }
</script>

<div class="sonos-strip" class:is-playing={isPlaying}>
  <div class="strip-art-wrap">
    {#if $sonos.art_url}
      <img src={$sonos.art_url} alt="Album art" class="strip-art" />
    {:else}
      <div class="strip-art strip-art-placeholder">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />
        </svg>
      </div>
    {/if}
  </div>

  <div class="strip-info">
    <div class="strip-track">{$sonos.track || 'Nothing playing'}</div>
    <div class="strip-artist">{$sonos.artist || '\u00A0'}</div>
  </div>

  <div class="strip-controls">
    <button class="strip-btn" on:click={onPrevious} aria-label="Previous">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg>
    </button>
    <button class="strip-btn strip-btn-play" on:click={onPlayPause} aria-label={isPlaying ? 'Pause' : 'Play'}>
      {#if isPlaying}
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>
      {:else}
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
      {/if}
    </button>
    <button class="strip-btn" on:click={onNext} aria-label="Next">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg>
    </button>
  </div>

  <div class="strip-volume">
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" class="strip-vol-icon">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
    </svg>
    <Slider value={$sonos.volume} min={0} max={100} onChange={onVolumeChange} liveUpdate={false} className="strip-vol-slider" />
  </div>
</div>

<style>
  .sonos-strip {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 16px;
    width: 100%;
  }

  .sonos-strip.is-playing .strip-track {
    animation: trackPulse 3s ease-in-out infinite;
  }

  @keyframes trackPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.88; }
  }

  @media (prefers-reduced-motion: reduce) {
    .sonos-strip.is-playing .strip-track { animation: none; }
  }

  .strip-art-wrap {
    flex-shrink: 0;
  }

  .strip-art {
    width: 56px;
    height: 56px;
    border-radius: 10px;
    object-fit: cover;
  }

  .strip-art-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-muted);
  }

  .strip-info {
    flex: 1;
    min-width: 0;
  }

  .strip-track {
    font-family: var(--font-body);
    font-size: 15px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .strip-artist {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: 2px;
  }

  .strip-controls {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .strip-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: transparent;
    color: var(--text-primary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s;
  }

  .strip-btn:hover {
    background: rgba(255, 255, 255, 0.06);
  }

  .strip-btn-play {
    width: 40px;
    height: 40px;
    background: rgba(255, 255, 255, 0.08);
  }

  .strip-btn-play:hover {
    background: rgba(255, 255, 255, 0.14);
  }

  .strip-volume {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
    width: 160px;
    overflow: hidden;
  }

  .strip-vol-icon {
    color: var(--text-muted);
    flex-shrink: 0;
  }

  @media (max-width: 768px) {
    .sonos-strip {
      flex-wrap: wrap;
      gap: 12px;
    }
    .strip-volume {
      width: 100%;
    }
  }
</style>
