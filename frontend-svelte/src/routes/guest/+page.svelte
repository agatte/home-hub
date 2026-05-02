<script>
  import { Music } from 'lucide-svelte'
  import { sonos } from '$lib/stores/sonos.js'

  // Three to six short lines, edit freely. Anything that helps a guest
  // feel oriented when Anthony's in the kitchen.
  const HOUSE_RULES = [
    'Make yourself at home — fridge and bar are open.',
    'Bathroom is past the kitchen on the left.',
    'Lights and music change with the room — that\'s normal.',
  ]

  $: nowPlaying = $sonos.state === 'PLAYING' && ($sonos.track || $sonos.artist)
</script>

<svelte:head>
  <title>Welcome — Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>Welcome</h1>
    <p class="guest-subtitle">Quick info to get you settled in</p>
  </header>

  <section class="guest-card guest-card-music">
    <div class="guest-card-head">
      <Music size={20} strokeWidth={1.5} />
      <h2>Now Playing</h2>
    </div>
    {#if nowPlaying}
      <div class="guest-track">
        {#if $sonos.art_url}
          <img class="guest-art" src={$sonos.art_url} alt="Album artwork" />
        {/if}
        <div class="guest-track-text">
          <div class="guest-track-title">{$sonos.track || '—'}</div>
          {#if $sonos.artist}
            <div class="guest-track-artist">{$sonos.artist}</div>
          {/if}
        </div>
      </div>
    {:else}
      <p class="guest-empty">Speaker is quiet.</p>
    {/if}
  </section>

  <section class="guest-card guest-card-rules">
    <div class="guest-card-head">
      <h2>House Notes</h2>
    </div>
    <ul class="guest-rules">
      {#each HOUSE_RULES as rule}
        <li>{rule}</li>
      {/each}
    </ul>
  </section>
</main>

<style>
  .guest-page {
    max-width: 540px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .guest-header {
    text-align: center;
    margin-bottom: 4px;
  }

  .guest-header h1 {
    font-family: var(--font-display);
    font-size: 56px;
    line-height: 1;
    margin: 0 0 8px;
    letter-spacing: 0.04em;
    color: #fff;
  }

  .guest-subtitle {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.65);
    margin: 0;
  }

  .guest-card {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 18px;
    padding: 22px 24px;
    backdrop-filter: blur(12px);
  }

  .guest-card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    color: rgba(245, 243, 238, 0.85);
  }

  .guest-card-head h2 {
    font-family: var(--font-display);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
    color: rgba(245, 243, 238, 0.95);
  }

  .guest-empty {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.55);
    margin: 0;
  }

  .guest-track {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .guest-art {
    width: 64px;
    height: 64px;
    border-radius: 8px;
    object-fit: cover;
    flex-shrink: 0;
  }

  .guest-track-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .guest-track-title {
    font-size: 16px;
    color: #fff;
    font-weight: 500;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .guest-track-artist {
    font-size: 13px;
    color: rgba(245, 243, 238, 0.7);
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .guest-rules {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .guest-rules li {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.85);
    line-height: 1.5;
    padding-left: 18px;
    position: relative;
  }

  .guest-rules li::before {
    content: '•';
    position: absolute;
    left: 4px;
    color: rgba(245, 243, 238, 0.4);
  }

  @media (max-width: 480px) {
    .guest-header h1 {
      font-size: 44px;
    }
  }
</style>
