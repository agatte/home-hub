<script>
  import { onMount } from 'svelte'
  import { Sprout, Droplets } from 'lucide-svelte'

  /** @type {{ total?: number, needs_water?: number, overdue?: number, healthy?: number, needs_attention?: number, next_watering?: any } | null} */
  let summary = null
  let loaded = false
  let unavailable = false

  onMount(async () => {
    try {
      const res = await fetch('/api/guest/plants')
      if (!res.ok) {
        unavailable = true
        return
      }
      const body = await res.json()
      summary = body.plant_summary ?? null
    } catch {
      unavailable = true
    } finally {
      loaded = true
    }
  })

  $: nextWatering = summary?.next_watering
  $: nextWateringText = (() => {
    if (!nextWatering) return null
    if (typeof nextWatering === 'string') return nextWatering
    if (nextWatering.name && nextWatering.due_in) {
      return `${nextWatering.name} â€” ${nextWatering.due_in}`
    }
    if (nextWatering.name) return nextWatering.name
    return null
  })()
</script>

<svelte:head>
  <title>Plants â€” Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>Plants</h1>
    <p class="guest-subtitle">What's growing here</p>
  </header>

  {#if !loaded}
    <section class="guest-card">
      <p class="muted">Loadingâ€¦</p>
    </section>
  {:else if unavailable || !summary}
    <section class="guest-card">
      <div class="card-head"><Sprout size={20} strokeWidth={1.5} /><h2>Plants</h2></div>
      <p class="muted">Plant app isn't set up here yet.</p>
    </section>
  {:else}
    <section class="guest-card">
      <div class="card-head">
        <Sprout size={20} strokeWidth={1.5} />
        <h2>Status</h2>
        {#if summary.overdue && summary.overdue > 0}
          <span class="chip chip-thirsty">{summary.overdue} overdue</span>
        {:else if summary.needs_water && summary.needs_water > 0}
          <span class="chip chip-warn">{summary.needs_water} thirsty</span>
        {/if}
      </div>
      <div class="stats">
        <div class="stat">
          <div class="stat-value">{summary.total ?? 'â€”'}</div>
          <div class="stat-label">Total</div>
        </div>
        <div class="stat">
          <div class="stat-value">{summary.healthy ?? (summary.total ?? 0) - (summary.needs_attention ?? 0)}</div>
          <div class="stat-label">Healthy</div>
        </div>
      </div>
    </section>

    {#if nextWateringText}
      <section class="guest-card">
        <div class="card-head">
          <Droplets size={20} strokeWidth={1.5} />
          <h2>Next watering</h2>
        </div>
        <p class="next-water">{nextWateringText}</p>
      </section>
    {/if}
  {/if}
</main>

<style>
  .guest-page {
    max-width: 540px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .guest-header { text-align: center; margin-bottom: 4px; }
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

  .card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    color: rgba(245, 243, 238, 0.85);
  }
  .card-head h2 {
    font-family: var(--font-display);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
    color: rgba(245, 243, 238, 0.95);
    flex: 1;
  }

  .chip {
    font-size: 11px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 999px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .chip-thirsty {
    background: rgba(248, 113, 113, 0.18);
    color: #fca5a5;
    border: 1px solid rgba(248, 113, 113, 0.4);
  }
  .chip-warn {
    background: rgba(251, 191, 36, 0.18);
    color: #fcd34d;
    border: 1px solid rgba(251, 191, 36, 0.4);
  }

  .stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .stat { text-align: center; }
  .stat-value {
    font-family: var(--font-display);
    font-size: 40px;
    line-height: 1;
    color: #fff;
  }
  .stat-label {
    font-size: 12px;
    color: rgba(245, 243, 238, 0.6);
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .next-water {
    font-size: 16px;
    color: #fff;
    margin: 0;
    line-height: 1.4;
  }

  .muted {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.55);
    margin: 0;
  }

  @media (max-width: 480px) {
    .guest-header h1 { font-size: 44px; }
    .stat-value { font-size: 34px; }
  }
</style>
