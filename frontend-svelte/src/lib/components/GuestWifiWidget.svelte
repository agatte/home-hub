<script>
  import { onMount, tick } from 'svelte'
  import QRCode from 'qrcode'
  import { Wifi } from 'lucide-svelte'
  import { apiGet } from '$lib/api.js'

  /** @type {{ configured: boolean, ssid?: string, password?: string, security?: string, qr_payload?: string } | null} */
  let info = null
  let error = false
  let modalOpen = false
  let qrDataUrl = ''
  let urlQrDataUrl = ''
  /** @type {HTMLButtonElement | undefined} */
  let closeBtn

  function portal(node) {
    document.body.appendChild(node)
    return {
      destroy() {
        if (node.parentNode === document.body) document.body.removeChild(node)
      },
    }
  }

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape' && modalOpen) modalOpen = false
  }

  async function fetchInfo() {
    try {
      const resp = await apiGet('/api/guest/wifi')
      info = resp
      error = false
    } catch {
      error = true
    }
  }

  async function openModal() {
    if (!info?.configured || !info.qr_payload) return
    try {
      qrDataUrl = await QRCode.toDataURL(info.qr_payload, {
        width: 360,
        margin: 1,
        color: { dark: '#000000', light: '#ffffff' },
      })
    } catch {
      qrDataUrl = ''
    }
    try {
      urlQrDataUrl = await QRCode.toDataURL(`${window.location.origin}/guest`, {
        width: 200,
        margin: 1,
        color: { dark: '#000000', light: '#ffffff' },
      })
    } catch {
      urlQrDataUrl = ''
    }
    modalOpen = true
    await tick()
    closeBtn?.focus()
  }

  onMount(() => {
    fetchInfo()
  })
</script>

<div class="wifi-content">
  <div class="wifi-main">
    <div class="wifi-icon">
      <Wifi size={28} strokeWidth={1.5} />
    </div>
    <div class="wifi-text">
      <div class="wifi-title">Guest WiFi</div>
      {#if info?.configured}
        <div class="wifi-ssid">{info.ssid}</div>
      {:else if error}
        <div class="wifi-empty">Service unavailable</div>
      {:else if info && !info.configured}
        <div class="wifi-empty">Not configured</div>
      {:else}
        <div class="wifi-empty">Loading...</div>
      {/if}
    </div>
  </div>

  {#if info?.configured}
    <button type="button" class="wifi-link" on:click={openModal}>
      Show QR &rarr;
    </button>
  {:else if info && !info.configured}
    <div class="wifi-hint">Set GUEST_WIFI_SSID + GUEST_WIFI_PASSWORD in .env</div>
  {/if}
</div>

<svelte:window on:keydown={handleKeydown} />

{#if modalOpen && info?.configured}
  <div
    class="wifi-modal-backdrop"
    use:portal
    on:click|self={() => (modalOpen = false)}
    role="presentation"
  >
    <button
      type="button"
      class="wifi-modal-close"
      bind:this={closeBtn}
      on:click={() => (modalOpen = false)}
      aria-label="Close guest WiFi"
    >
      ✕
    </button>
    <div class="wifi-modal-content">
      <div class="wifi-modal-title">Guest WiFi</div>
      <div class="wifi-modal-subtitle">Point your camera at the code</div>
      {#if qrDataUrl}
        <img class="wifi-modal-image" src={qrDataUrl} alt="QR code to join guest WiFi" />
      {:else}
        <div class="wifi-modal-fallback">Could not generate QR code.</div>
      {/if}
      <dl class="wifi-modal-creds">
        <div class="wifi-modal-cred">
          <dt>Network</dt>
          <dd>{info.ssid}</dd>
        </div>
      </dl>
      {#if urlQrDataUrl}
        <div class="wifi-modal-step2">
          <div class="wifi-modal-step2-label">Then scan for tonight's info</div>
          <img class="wifi-modal-image-small" src={urlQrDataUrl} alt="QR code to /guest landing page" />
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .wifi-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .wifi-main {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .wifi-icon {
    color: var(--accent);
    flex-shrink: 0;
  }

  .wifi-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .wifi-title {
    font-family: var(--font-display);
    font-size: 22px;
    line-height: 1;
    color: var(--text-primary);
  }

  .wifi-ssid {
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .wifi-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
  }

  .wifi-hint {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  .wifi-link {
    appearance: none;
    background: none;
    border: none;
    padding: 0;
    align-self: flex-start;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
    transition: color 0.15s;
  }

  .wifi-link:hover {
    color: var(--text-primary);
  }

  .wifi-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.88);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .wifi-modal-content {
    background: #fff;
    color: #000;
    border-radius: 20px;
    padding: 32px 36px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    max-width: 440px;
    width: 100%;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .wifi-modal-title {
    font-family: var(--font-display);
    font-size: 32px;
    line-height: 1;
    text-align: center;
    letter-spacing: 0.02em;
  }

  .wifi-modal-subtitle {
    font-family: var(--font-body);
    font-size: 14px;
    color: #555;
    text-align: center;
  }

  .wifi-modal-image {
    width: 320px;
    height: 320px;
    display: block;
    margin: 4px 0;
  }

  .wifi-modal-fallback {
    font-family: var(--font-body);
    font-size: 13px;
    color: #b00;
    padding: 24px;
  }

  .wifi-modal-creds {
    margin: 4px 0 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .wifi-modal-cred {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 16px;
    border-top: 1px solid #eee;
    padding-top: 8px;
  }

  .wifi-modal-cred dt {
    font-family: var(--font-body);
    font-size: 12px;
    color: #777;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0;
  }

  .wifi-modal-cred dd {
    font-family: var(--font-body);
    font-size: 18px;
    font-weight: 500;
    color: #111;
    margin: 0;
    text-align: right;
    word-break: break-all;
  }

  .wifi-modal-step2 {
    margin-top: 8px;
    padding-top: 14px;
    border-top: 1px solid #eee;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
  }

  .wifi-modal-step2-label {
    font-family: var(--font-body);
    font-size: 12px;
    color: #777;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .wifi-modal-image-small {
    width: 160px;
    height: 160px;
    display: block;
  }

  .wifi-modal-close {
    position: fixed;
    top: 16px;
    right: 16px;
    z-index: 1001;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.7);
    color: #fff;
    border: 2px solid rgba(255, 255, 255, 0.4);
    font-size: 22px;
    line-height: 1;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s, transform 0.15s;
  }

  .wifi-modal-close:hover {
    background: rgba(0, 0, 0, 0.9);
    transform: scale(1.05);
  }

  @media (max-width: 480px) {
    .wifi-modal-backdrop {
      padding: 12px;
    }
    .wifi-modal-image {
      width: 260px;
      height: 260px;
    }
    .wifi-modal-content {
      padding: 24px 20px;
    }
  }
</style>
