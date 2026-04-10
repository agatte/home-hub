<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { Sprout, Droplets, AlertTriangle } from 'lucide-svelte'

  const PLANT_APP_URL = 'https://plant-care-app-gamma.vercel.app'

  /** @type {{ total: number, needs_water: number, overdue: number, healthy: number, needs_attention: number, next_watering: { plant: string, label: string } | null } | null} */
  let summary = null
  let error = false
  let refreshInterval

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

    <a href={PLANT_APP_URL} target="_blank" rel="noopener" class="plant-link">
      View Plants &rarr;
    </a>
  </div>
{:else if error}
  <div class="plant-empty">Plant app unavailable</div>
{:else}
  <div class="plant-empty">Loading...</div>
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
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
    margin-top: 4px;
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
</style>
