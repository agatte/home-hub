<script>
  import { tick } from 'svelte'
  import QRCode from 'qrcode'

  /** @type {any} */
  export let rec
  /** @type {(id: number, action: 'liked' | 'dismissed') => void} */
  export let onFeedback = () => {}
  /** @type {(previewUrl: string) => Promise<void>} */
  export let onPreview = async () => {}

  let previewing = false
  let qrOpen = false
  let qrDataUrl = ''
  /** @type {HTMLButtonElement | undefined} */
  let closeBtn

  // Portal action — re-parent the modal to document.body so position:fixed
  // escapes any backdrop-filter ancestor (the .widget container on parent
  // pages would otherwise become its containing block).
  /** @param {HTMLElement} node */
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
    if (e.key === 'Escape' && qrOpen) qrOpen = false
  }

  async function handlePreview() {
    if (!rec.preview_url) return
    previewing = true
    await onPreview(rec.preview_url)
    setTimeout(() => { previewing = false }, 3000)
  }

  async function openQrModal() {
    if (!rec.itunes_url) return
    try {
      qrDataUrl = await QRCode.toDataURL(rec.itunes_url, {
        width: 280,
        margin: 1,
        color: { dark: '#000000', light: '#ffffff' },
      })
    } catch {
      qrDataUrl = ''
    }
    qrOpen = true
    await tick()
    closeBtn?.focus()
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
      <button class="rec-action-btn rec-apple-btn" on:click={openQrModal} title="Show QR for Apple Music">
        <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 3l3 3-3 3" />
          <path d="M3 10V8a4 4 0 0 1 4-4h10" />
        </svg>
      </button>
    {/if}
  </div>
</div>

<svelte:window on:keydown={handleKeydown} />

{#if qrOpen}
  <div
    class="qr-modal-backdrop"
    use:portal
    on:click|self={() => (qrOpen = false)}
    role="presentation"
  >
    <button
      type="button"
      class="qr-modal-close"
      bind:this={closeBtn}
      on:click={() => (qrOpen = false)}
      aria-label="Close QR code"
    >
      ✕
    </button>
    <div class="qr-modal-content">
      <div class="qr-modal-title">{rec.artist_name}</div>
      {#if rec.track_name}
        <div class="qr-modal-subtitle">{rec.track_name}</div>
      {/if}
      {#if qrDataUrl}
        <img class="qr-modal-image" src={qrDataUrl} alt="QR code for Apple Music link" />
      {:else}
        <div class="qr-modal-fallback">Could not generate QR code.</div>
      {/if}
      <div class="qr-modal-instruction">Scan with your phone to open in Apple Music</div>
    </div>
  </div>
{/if}

<style>
  .qr-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .qr-modal-content {
    background: #fff;
    color: #000;
    border-radius: 16px;
    padding: 28px 32px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    max-width: 360px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .qr-modal-title {
    font-family: var(--font-display);
    font-size: 26px;
    line-height: 1.1;
    text-align: center;
  }

  .qr-modal-subtitle {
    font-family: var(--font-body);
    font-size: 14px;
    color: #555;
    text-align: center;
  }

  .qr-modal-image {
    width: 280px;
    height: 280px;
    display: block;
    margin-top: 4px;
  }

  .qr-modal-fallback {
    font-family: var(--font-body);
    font-size: 13px;
    color: #b00;
    padding: 24px;
  }

  .qr-modal-instruction {
    font-family: var(--font-body);
    font-size: 12px;
    color: #666;
    text-align: center;
    margin-top: 4px;
  }

  .qr-modal-close {
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

  .qr-modal-close:hover {
    background: rgba(0, 0, 0, 0.9);
    transform: scale(1.05);
  }

  @media (max-width: 480px) {
    .qr-modal-backdrop {
      padding: 12px;
    }
    .qr-modal-image {
      width: 240px;
      height: 240px;
    }
  }
</style>
