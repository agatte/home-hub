<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { apiGet } from '$lib/api.js'

  const PIHOLE_ADMIN_URL = 'http://192.168.1.210:8080/admin'

  /** @param {HTMLElement} node */
  function portal(node) {
    document.body.appendChild(node)
    return {
      destroy() {
        if (node.parentNode === document.body) document.body.removeChild(node)
      },
    }
  }

  /** @type {{ total_queries: number, blocked: number, percent_blocked: number, domains_on_blocklist: number, active_clients: number, unique_domains: number, forwarded: number, cached: number } | null} */
  let stats = null
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

  async function fetchStats() {
    try {
      const resp = await apiGet('/api/pihole/stats')
      stats = resp.pihole
      error = false
    } catch {
      error = true
    }
  }

  /** @param {number} n */
  function fmtNum(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
    return n.toLocaleString()
  }

  onMount(() => {
    fetchStats()
    refreshInterval = setInterval(fetchStats, 60000) // 1 min
  })

  onDestroy(() => {
    clearInterval(refreshInterval)
  })
</script>

{#if stats}
  <div class="pihole-content">
    <div class="pihole-main">
      <div class="pihole-icon">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      </div>
      <div class="pihole-blocked">
        <span class="pihole-pct">{stats.percent_blocked}%</span>
        <span class="pihole-label">blocked</span>
      </div>
    </div>

    <div class="pihole-stats">
      <div class="pihole-stat">
        <span class="pihole-stat-value">{fmtNum(stats.total_queries)}</span>
        <span class="pihole-stat-label">queries</span>
      </div>
      <div class="pihole-stat">
        <span class="pihole-stat-value">{fmtNum(stats.blocked)}</span>
        <span class="pihole-stat-label">blocked</span>
      </div>
      <div class="pihole-stat">
        <span class="pihole-stat-value">{fmtNum(stats.domains_on_blocklist)}</span>
        <span class="pihole-stat-label">blocklist</span>
      </div>
      <div class="pihole-stat">
        <span class="pihole-stat-value">{stats.active_clients}</span>
        <span class="pihole-stat-label">clients</span>
      </div>
    </div>

    <button type="button" class="pihole-admin" on:click={openModal}>
      Open Admin
      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
        <polyline points="15 3 21 3 21 9" />
        <line x1="10" y1="14" x2="21" y2="3" />
      </svg>
    </button>
  </div>
{:else if error}
  <div class="pihole-empty">Pi-hole unavailable</div>
{:else}
  <div class="pihole-empty">Loading...</div>
{/if}

<svelte:window on:keydown={handleKeydown} />

{#if modalOpen}
  <div
    class="pihole-modal-backdrop"
    use:portal
    on:click|self={() => (modalOpen = false)}
    role="presentation"
  >
    <button
      type="button"
      class="pihole-modal-close"
      bind:this={closeBtn}
      on:click={() => (modalOpen = false)}
      aria-label="Close Pi-hole admin"
    >
      ✕
    </button>
    <iframe
      class="pihole-modal-iframe"
      src={PIHOLE_ADMIN_URL}
      title="Pi-hole Admin"
      allow="fullscreen"
    ></iframe>
  </div>
{/if}

<style>
  .pihole-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .pihole-main {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .pihole-icon {
    color: var(--text-secondary);
    flex-shrink: 0;
  }

  .pihole-blocked {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .pihole-pct {
    font-family: var(--font-display);
    font-size: 42px;
    font-weight: 400;
    line-height: 1;
    color: var(--text-primary);
    letter-spacing: 0.02em;
  }

  .pihole-label {
    font-family: var(--font-body);
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .pihole-stats {
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }

  .pihole-stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .pihole-stat-value {
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 400;
    color: var(--text-primary);
    letter-spacing: 0.02em;
    line-height: 1;
  }

  .pihole-stat-label {
    font-family: var(--font-body);
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .pihole-admin {
    appearance: none;
    background: none;
    border: none;
    padding: 0;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    margin-top: 2px;
    cursor: pointer;
    transition: color 0.2s;
  }

  .pihole-admin:hover {
    color: var(--text-secondary);
  }

  .pihole-empty {
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    padding: 8px 0;
  }

  .pihole-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }

  .pihole-modal-iframe {
    width: 100%;
    height: 100%;
    max-width: 1100px;
    max-height: 88vh;
    border: 0;
    border-radius: 12px;
    background: #fff;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  }

  .pihole-modal-close {
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

  .pihole-modal-close:hover {
    background: rgba(0, 0, 0, 0.9);
    transform: scale(1.05);
  }

  @media (max-width: 480px) {
    .pihole-modal-backdrop {
      padding: 12px;
    }
  }
</style>
