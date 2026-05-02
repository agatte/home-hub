<script>
  import { onMount } from 'svelte'
  import QRCode from 'qrcode'
  import { Wifi, Music } from 'lucide-svelte'
  import { apiGet } from '$lib/api.js'
  import { sonos } from '$lib/stores/sonos.js'

  /** @type {{ configured: boolean, ssid?: string, password?: string, qr_payload?: string } | null} */
  let info = null
  let qrDataUrl = ''
  let loadError = false

  // Three to six short lines, edit freely. Anything that helps a guest
  // feel oriented when Anthony's in the kitchen.
  const HOUSE_RULES = [
    'Make yourself at home — fridge and bar are open.',
    'The cat is friendly but skittish; let her come to you.',
    'Bathroom is past the kitchen on the left.',
    'Lights and music change with the room — that\'s normal.',
  ]

  async function loadInfo() {
    try {
      const resp = await apiGet('/api/guest/wifi')
      info = resp
      if (resp?.configured && resp.qr_payload) {
        qrDataUrl = await QRCode.toDataURL(resp.qr_payload, {
          width: 360,
          margin: 1,
          color: { dark: '#000000', light: '#ffffff' },
        })
      }
    } catch {
      loadError = true
    }
  }

  $: nowPlaying = $sonos.state === 'PLAYING' && ($sonos.track || $sonos.artist)

  onMount(() => {
    loadInfo()
  })
</script>

<svelte:head>
  <title>Welcome — Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>Welcome</h1>
    <p class="guest-subtitle">Quick info to get you settled in</p>
  </header>

  <section class="guest-card guest-card-wifi">
    <div class="guest-card-head">
      <Wifi size={20} strokeWidth={1.5} />
      <h2>WiFi</h2>
    </div>

    {#if info?.configured && qrDataUrl}
      <img class="guest-qr" src={qrDataUrl} alt="QR code to join the WiFi" />
      <dl class="guest-creds">
        <div>
          <dt>Network</dt>
          <dd>{info.ssid}</dd>
        </div>
        <div>
          <dt>Password</dt>
          <dd class="guest-creds-pw">{info.password}</dd>
        </div>
      </dl>
      <p class="guest-hint">Point your phone camera at the code to join.</p>
    {:else if info && !info.configured}
      <p class="guest-empty">Ask Anthony for the password.</p>
    {:else if loadError}
      <p class="guest-empty">WiFi info unavailable right now.</p>
    {:else}
      <p class="guest-empty">Loading…</p>
    {/if}
  </section>

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

  .guest-card-wifi {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .guest-qr {
    width: 280px;
    height: 280px;
    background: #fff;
    border-radius: 12px;
    padding: 10px;
    box-sizing: content-box;
    margin-bottom: 18px;
  }

  .guest-creds {
    width: 100%;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .guest-creds > div {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    padding-top: 10px;
  }

  .guest-creds dt {
    font-size: 11px;
    color: rgba(245, 243, 238, 0.6);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 0;
  }

  .guest-creds dd {
    font-size: 18px;
    color: #fff;
    margin: 0;
    text-align: right;
    word-break: break-all;
    font-weight: 500;
  }

  .guest-creds-pw {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 16px !important;
  }

  .guest-hint {
    font-size: 12px;
    color: rgba(245, 243, 238, 0.55);
    margin: 14px 0 0;
    text-align: center;
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
    .guest-qr {
      width: 240px;
      height: 240px;
    }
  }
</style>
