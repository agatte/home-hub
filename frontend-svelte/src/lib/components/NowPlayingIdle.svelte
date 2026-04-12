<script>
  import { sonos } from '$lib/stores/sonos.js'
  import { userIdle } from '$lib/stores/activity.js'

  $: playing = $sonos.state === 'PLAYING'
  $: track = $sonos.track || ''
  $: artist = $sonos.artist || ''
  $: artUrl = $sonos.art_url || ''
  $: visible = $userIdle && playing && track.length > 0
</script>

<div class="now-playing-idle" class:visible>
  {#if artUrl}
    <div class="art-glow" style="background-image: url({artUrl})" />
  {/if}
  <div class="text-container">
    <div class="idle-track">{track}</div>
    {#if artist}
      <div class="idle-artist">{artist}</div>
    {/if}
  </div>
</div>

<style>
  .now-playing-idle {
    position: fixed;
    inset: 0;
    z-index: 35;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    opacity: 0;
    transition: opacity 1.2s ease;
  }

  .now-playing-idle.visible {
    opacity: 1;
  }

  /* Blurred album art as ambient background glow */
  .art-glow {
    position: absolute;
    inset: -40px;
    background-size: cover;
    background-position: center;
    filter: blur(80px) saturate(1.6) brightness(0.3);
    opacity: 0.5;
  }

  .text-container {
    position: relative;
    text-align: center;
    padding: 2rem;
    max-width: 90vw;
  }

  .idle-track {
    font-family: var(--font-display);
    font-size: clamp(3.5rem, 9vw, 7.5rem);
    line-height: 1.05;
    color: rgba(255, 255, 255, 0.85);
    letter-spacing: 0.02em;
    text-transform: uppercase;
    text-shadow: 0 0 60px rgba(255, 255, 255, 0.08);
    word-break: break-word;
    animation: textFloat 8s ease-in-out infinite;
  }

  .idle-artist {
    font-family: var(--font-body);
    font-size: clamp(1.2rem, 3vw, 2rem);
    color: rgba(255, 255, 255, 0.45);
    margin-top: 0.5rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }

  @keyframes textFloat {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
  }

  @media (prefers-reduced-motion: reduce) {
    .idle-track { animation: none; }
    .now-playing-idle { transition-duration: 0.3s; }
  }

  @media (max-width: 768px) {
    .idle-track {
      font-size: clamp(2rem, 8vw, 4rem);
    }
    .idle-artist {
      font-size: clamp(0.9rem, 2.5vw, 1.2rem);
    }
  }
</style>
