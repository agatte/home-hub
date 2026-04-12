<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { Sprout, Droplets, AlertTriangle } from 'lucide-svelte'

  const PLANT_APP_URL = 'https://plant-care-app-gamma.vercel.app'

  // Portal action — moves the node to document.body so position:fixed escapes
  // the .widget ancestor's backdrop-filter containing block.
  /** @param {HTMLElement} node */
  function portal(node) {
    document.body.appendChild(node)
    return {
      destroy() {
        if (node.parentNode === document.body) document.body.removeChild(node)
      },
    }
  }

  /** @type {{ total: number, needs_water: number, overdue: number, healthy: number, needs_attention: number, next_watering: { plant: string, label: string } | null } | null} */
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
    // Focus the close button so ESC works before the iframe steals focus.
    // After the user clicks into the iframe, ESC keystrokes go to the iframe
    // and our window listener can't see them — the X button stays as the
    // always-available escape path.
    await tick()
    closeBtn?.focus()
  }

  async function fetchStatus() {
    try {
      const resp = await apiGet('/api/plants/status')
      summary = resp.plant_summary
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
  <div class="plant-content">
    <div class="plant-main">
      <div class="plant-icon">
        <Sprout size={28} strokeWidth={1.5} />
      </div>
      <div class="plant-count">{summary.total}</div>
      <span class="plant-count-label">plants</span>
    </div>

    <div class="plant-stats">
      {#if summary.needs_water > 0}
        <div class="plant-stat stat-water">
          <Droplets size={14} strokeWidth={1.5} />
          <span>{summary.needs_water} need water</span>
        </div>
      {/if}
      {#if summary.overdue > 0}
        <div class="plant-stat stat-overdue">
          <AlertTriangle size={14} strokeWidth={1.5} />
          <span>{summary.overdue} overdue</span>
        </div>
      {/if}
      {#if summary.needs_water === 0 && summary.overdue === 0}
        <div class="plant-stat stat-ok">
          <span>All plants happy</span>
        </div>
      {/if}
    </div>

    {#if summary.next_watering}
      <div class="plant-next">
        Water <strong>{summary.next_watering.plant}</strong> {summary.next_watering.label}
      </div>
    {/if}

    <button type="button" class="plant-link" on:click={openModal}>
      View Plants &rarr;
    </button>
  </div>
{:else if error}
  <div class="plant-empty">Plant app unavailable</div>
{:else}
  <div class="plant-empty">Loading...</div>
{/if}

<svelte:window on:keydown={handleKeydown} />

{#if modalOpen}
  <div
    class="plant-modal-backdrop"
    use:portal
    on:click|self={() => (modalOpen = false)}
    role="presentation"
  >
    <button
      type="button"
      class="plant-modal-close"
      bind:this={closeBtn}
      on:click={() => (modalOpen = false)}
      aria-label="Close plant app"
    >
      ✕
    </button>
    <iframe
      class="plant-modal-iframe"
      src={PLANT_APP_URL}
      title="Plant Care App"
      allow="fullscreen"
    ></iframe>
  </div>
{/if}

<style>
  .plant-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .plant-main {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .plant-icon {
    color: var(--success);
    flex-shrink: 0;
  }

  .plant-count {
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 400;
    line-height: 1;
    color: var(--text-primary);
  }

  .plant-count-label {
    font-family: var(--font-body);
    font-size: 14px;
    color: var(--text-secondary);
    align-self: flex-end;
    margin-bottom: 4px;
  }

  .plant-stats {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .plant-stat {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-body);
    font-size: 13px;
  }

  .stat-water {
    color: var(--warning);
  }

  .stat-overdue {
    color: var(--danger);
  }

  .stat-ok {
    color: var(--success);
  }

  .plant-next {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-secondary);
  }

  .plant-next strong {
    color: var(--text-primary);
    font-weight: 500;
  }

  .plant-link {
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

  .plant-link:hover {
    color: var(--text-primary);
  }

  .plant-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
  }

  .plant-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .plant-modal-iframe {
    width: 100%;
    height: 100%;
    max-width: 1100px;
    max-height: 88vh;
    border: 0;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .plant-modal-close {
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

  .plant-modal-close:hover {
    background: rgba(0, 0, 0, 0.9);
    transform: scale(1.05);
  }

  @media (max-width: 480px) {
    .plant-modal-backdrop {
      padding: 12px;
    }
  }
</style>
