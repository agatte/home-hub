<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { Wine, PartyPopper, AlertTriangle } from 'lucide-svelte'

  // Bar app URL for iframe modal — read from the status response
  let barAppUrl = ''

  function portal(node) {
    document.body.appendChild(node)
    return {
      destroy() {
        if (node.parentNode === document.body) document.body.removeChild(node)
      },
    }
  }

  /** @type {{ total_bottles: number, low_stock_count: number, total_recipes: number, makeable_count: number, party_mode: boolean, pending_orders: number, session_name: string | null, cocktail_suggestion: { name: string, slug: string, image_url: string | null } | null } | null} */
  let summary = null
  let error = false
  let refreshInterval
  let modalOpen = false
  /** @type {HTMLButtonElement | undefined} */
  let closeBtn

  /** @param {KeyboardEvent} e */
  function handleKeydown(e) {
    if (e.key === 'Escape' && modalOpen) modalOpen = false
  }

  async function openModal() {
    modalOpen = true
    await tick()
    closeBtn?.focus()
  }

  async function fetchStatus() {
    try {
      const resp = await apiGet('/api/bar/status')
      summary = resp.bar_summary
      if (resp.bar_app_url) barAppUrl = resp.bar_app_url
      error = false
    } catch {
      error = true
    }
  }

  onMount(() => {
    fetchStatus()
    refreshInterval = setInterval(fetchStatus, 600000) // 10 min
  })

  onDestroy(() => {
    clearInterval(refreshInterval)
  })
</script>

{#if summary}
  <div class="bar-content">
    <div class="bar-main">
      <div class="bar-icon">
        <Wine size={28} strokeWidth={1.5} />
      </div>
      <div class="bar-count">{summary.total_bottles}</div>
      <span class="bar-count-label">bottles</span>
    </div>

    <div class="bar-stats">
      <div class="bar-stat stat-makeable">
        <span>{summary.makeable_count} cocktails ready</span>
      </div>
      {#if summary.low_stock_count > 0}
        <div class="bar-stat stat-low">
          <AlertTriangle size={14} strokeWidth={1.5} />
          <span>{summary.low_stock_count} low stock</span>
        </div>
      {/if}
      {#if summary.party_mode}
        <div class="bar-stat stat-party">
          <PartyPopper size={14} strokeWidth={1.5} />
          <span>Party mode{summary.session_name ? `: ${summary.session_name}` : ''}</span>
        </div>
        {#if summary.pending_orders > 0}
          <div class="bar-stat stat-orders">
            <span>{summary.pending_orders} pending order{summary.pending_orders !== 1 ? 's' : ''}</span>
          </div>
        {/if}
      {/if}
    </div>

    {#if summary.cocktail_suggestion}
      <div class="bar-suggestion">
        Try a <strong>{summary.cocktail_suggestion.name}</strong>
      </div>
    {/if}

    <button type="button" class="bar-link" on:click={openModal}>
      View Bar &rarr;
    </button>
  </div>
{:else if error}
  <div class="bar-empty">Bar app unavailable</div>
{:else}
  <div class="bar-empty">Loading...</div>
{/if}

<svelte:window on:keydown={handleKeydown} />

{#if modalOpen}
  <div
    class="bar-modal-backdrop"
    use:portal
    on:click|self={() => (modalOpen = false)}
    role="presentation"
  >
    <button
      type="button"
      class="bar-modal-close"
      bind:this={closeBtn}
      on:click={() => (modalOpen = false)}
      aria-label="Close bar app"
    >
      ✕
    </button>
    <iframe
      class="bar-modal-iframe"
      src={barAppUrl}
      title="Home Bar"
      allow="fullscreen"
    ></iframe>
  </div>
{/if}

<style>
  .bar-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .bar-main {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .bar-icon {
    color: var(--accent);
    flex-shrink: 0;
  }

  .bar-count {
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 400;
    line-height: 1;
    color: var(--text-primary);
  }

  .bar-count-label {
    font-family: var(--font-body);
    font-size: 14px;
    color: var(--text-secondary);
    align-self: flex-end;
    margin-bottom: 4px;
  }

  .bar-stats {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .bar-stat {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-body);
    font-size: 13px;
  }

  .stat-makeable {
    color: var(--success);
  }

  .stat-low {
    color: var(--warning);
  }

  .stat-party {
    color: var(--accent);
  }

  .stat-orders {
    color: var(--accent);
    font-weight: 500;
  }

  .bar-suggestion {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-secondary);
  }

  .bar-suggestion strong {
    color: var(--text-primary);
    font-weight: 500;
  }

  .bar-link {
    appearance: none;
    background: none;
    border: none;
    padding: 0;
    align-self: flex-start;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
    margin-top: 4px;
    cursor: pointer;
    transition: color 0.15s;
  }

  .bar-link:hover {
    color: var(--text-primary);
  }

  .bar-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
  }

  .bar-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .bar-modal-iframe {
    width: 100%;
    height: 100%;
    max-width: 1100px;
    max-height: 88vh;
    border: 0;
    border-radius: 12px;
    background: #0a0a0a;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .bar-modal-close {
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

  .bar-modal-close:hover {
    background: rgba(0, 0, 0, 0.9);
    transform: scale(1.05);
  }

  @media (max-width: 480px) {
    .bar-modal-backdrop {
      padding: 12px;
    }
  }
</style>
