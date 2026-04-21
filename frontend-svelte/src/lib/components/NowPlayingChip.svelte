<script>
  import { sonos } from '$lib/stores/sonos.js'

  $: playing = $sonos.state === 'PLAYING'
  $: track = $sonos.track || ''
  $: artist = $sonos.artist || ''
  $: artUrl = $sonos.art_url || ''
  $: hasTrack = track.length > 0
</script>

{#if hasTrack}
  <a href="/music" class="now-playing-chip" class:is-playing={playing}>
    {#if artUrl}
      <img class="chip-art" src={artUrl} alt="" width="32" height="32" />
    {:else}
      <div class="chip-art chip-art-placeholder">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" /></svg>
      </div>
    {/if}
    <div class="chip-text">
      <div class="chip-track">{track}</div>
      {#if artist}
        <div class="chip-artist">{artist}</div>
      {/if}
    </div>
  </a>
{/if}

<style>
  .now-playing-chip {
    position: fixed;
    bottom: calc(20px + env(safe-area-inset-bottom, 0px));
    right: calc(20px + env(safe-area-inset-right, 0px));
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 14px 6px 6px;
    background: rgba(10, 10, 15, 0.55);
    backdrop-filter: blur(16px) saturate(1.2);
    -webkit-backdrop-filter: blur(16px) saturate(1.2);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 999px;
    z-index: 45;
    text-decoration: none;
    color: inherit;
    max-width: 280px;
    transition: border-color 0.2s, opacity 0.3s;
    cursor: pointer;
  }

  .now-playing-chip:hover {
    border-color: rgba(255, 255, 255, 0.12);
  }

  .now-playing-chip.is-playing {
    animation: chipPulse 3s ease-in-out infinite;
  }

  @keyframes chipPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.88; }
  }

  @media (prefers-reduced-motion: reduce) {
    .now-playing-chip.is-playing { animation: none; }
  }

  .chip-art {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }

  .chip-art-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-muted);
  }

  .chip-text {
    min-width: 0;
    overflow: hidden;
  }

  .chip-track {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .chip-artist {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  @media (max-width: 768px) {
    .now-playing-chip {
      bottom: calc(76px + env(safe-area-inset-bottom, 0px));
      right: calc(12px + env(safe-area-inset-right, 0px));
      max-width: 200px;
    }
  }

  @media (max-width: 480px) {
    .now-playing-chip {
      bottom: calc(64px + env(safe-area-inset-bottom, 0px));
      right: calc(8px + env(safe-area-inset-right, 0px));
      max-width: 180px;
    }
  }
</style>
