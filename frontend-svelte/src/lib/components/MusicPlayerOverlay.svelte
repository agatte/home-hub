<script>
  import { ExternalLink, Music, Pause, Play, SkipBack, SkipForward, Volume2, X } from 'lucide-svelte'
  import Slider from './Slider.svelte'
  import { sonos } from '$lib/stores/sonos.js'
  import { sonosCommand } from '$lib/stores/init.js'
  import { closeMusicPlayer, musicPlayerOpen } from '$lib/stores/musicPlayer.js'

  $: isPlaying = $sonos.state === 'PLAYING'
  $: track = $sonos.track || 'Nothing playing'
  $: artist = $sonos.artist || ''
  $: album = $sonos.album || ''
  $: artUrl = $sonos.art_url || ''

  /** @param {KeyboardEvent} event */
  function handleKeydown(event) {
    if (event.key === 'Escape' && $musicPlayerOpen) closeMusicPlayer()
  }

  /** @param {number} volume */
  function onVolumeChange(volume) {
    sonosCommand('volume', { volume })
  }

  function onPrevious() { sonosCommand('previous') }
  function onNext() { sonosCommand('next') }
  function onPlayPause() { sonosCommand(isPlaying ? 'pause' : 'play') }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if $musicPlayerOpen}
  <div class="music-player-backdrop">
    <button type="button" class="backdrop-close" aria-label="Close music player" on:click={closeMusicPlayer}></button>

    <section
      class="music-player"
      role="dialog"
      aria-modal="true"
      aria-label="Music player"
    >
      <button type="button" class="icon-button close-button" aria-label="Close music player" on:click={closeMusicPlayer}>
        <X size={20} strokeWidth={1.8} />
      </button>

      <div class="player-art-wrap">
        {#if artUrl}
          <img class="player-art" src={artUrl} alt="" />
        {:else}
          <div class="player-art player-art-placeholder">
            <Music size={42} strokeWidth={1.4} />
          </div>
        {/if}
      </div>

      <div class="player-meta">
        <div class="player-kicker">{isPlaying ? 'Playing now' : 'Ready'}</div>
        <h2>{track}</h2>
        {#if artist}
          <p>{artist}</p>
        {:else if album}
          <p>{album}</p>
        {:else}
          <p>Sonos</p>
        {/if}
      </div>

      <div class="player-controls" aria-label="Playback controls">
        <button type="button" class="icon-button transport-button" aria-label="Previous" on:click={onPrevious}>
          <SkipBack size={22} strokeWidth={1.8} />
        </button>
        <button type="button" class="play-button" aria-label={isPlaying ? 'Pause' : 'Play'} on:click={onPlayPause}>
          {#if isPlaying}
            <Pause size={28} fill="currentColor" strokeWidth={0} />
          {:else}
            <Play size={28} fill="currentColor" strokeWidth={0} />
          {/if}
        </button>
        <button type="button" class="icon-button transport-button" aria-label="Next" on:click={onNext}>
          <SkipForward size={22} strokeWidth={1.8} />
        </button>
      </div>

      <div class="volume-row">
        <Volume2 size={18} strokeWidth={1.8} />
        <Slider value={$sonos.volume} min={0} max={100} onChange={onVolumeChange} liveUpdate={false} className="player-volume-slider" />
      </div>

      <a class="music-page-link" href="/music" on:click={closeMusicPlayer}>
        <ExternalLink size={16} strokeWidth={1.8} />
        <span>Open Music</span>
      </a>
    </section>
  </div>
{/if}

<style>
  .music-player-backdrop {
    position: fixed;
    inset: 0;
    z-index: 2000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: rgba(4, 5, 9, 0.5);
    backdrop-filter: blur(18px) saturate(1.1);
    -webkit-backdrop-filter: blur(18px) saturate(1.1);
  }

  .backdrop-close {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    border: 0;
    background: transparent;
    cursor: default;
  }

  .music-player {
    position: relative;
    display: grid;
    width: min(440px, calc(100vw - 32px));
    max-height: calc(100dvh - 48px);
    overflow: auto;
    gap: 18px;
    padding: 22px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.075), rgba(255, 255, 255, 0.035)),
      rgba(10, 10, 15, 0.88);
    box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
  }

  .close-button {
    position: absolute;
    top: 12px;
    right: 12px;
  }

  .icon-button,
  .play-button {
    border: 0;
    color: var(--text-primary);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .icon-button {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.06);
  }

  .icon-button:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .player-art-wrap {
    width: min(72vw, 260px);
    aspect-ratio: 1;
    justify-self: center;
    margin-top: 10px;
  }

  .player-art {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
    border-radius: 8px;
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.35);
  }

  .player-art-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-secondary);
  }

  .player-meta {
    min-width: 0;
    text-align: center;
  }

  .player-kicker {
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin-bottom: 6px;
  }

  .player-meta h2 {
    font-family: var(--font-body);
    font-size: clamp(22px, 5vw, 30px);
    font-weight: 650;
    line-height: 1.08;
    color: var(--text-primary);
    overflow-wrap: anywhere;
  }

  .player-meta p {
    margin-top: 6px;
    font-size: 15px;
    color: var(--text-secondary);
    overflow-wrap: anywhere;
  }

  .player-controls {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
  }

  .transport-button {
    width: 46px;
    height: 46px;
  }

  .play-button {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.92);
    color: #08080c;
  }

  .play-button:hover {
    background: #fff;
  }

  .volume-row {
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr);
    align-items: center;
    gap: 12px;
    color: var(--text-secondary);
  }

  .music-page-link {
    justify-self: center;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 40px;
    padding: 0 12px;
    color: var(--text-secondary);
    text-decoration: none;
    border-radius: 8px;
  }

  .music-page-link:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
  }

  @media (max-width: 480px) {
    .music-player-backdrop {
      align-items: flex-end;
      padding: 12px 12px calc(34px + env(safe-area-inset-bottom, 0px));
    }

    .music-player {
      width: 100%;
      gap: 16px;
      padding: 18px;
    }

    .player-art-wrap {
      width: min(62vw, 220px);
    }
  }
</style>