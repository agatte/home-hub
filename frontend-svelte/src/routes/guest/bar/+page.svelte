<script>
  import { onMount } from 'svelte'
  import { Wine, ExternalLink, Sparkles } from 'lucide-svelte'

  /** @type {{ total_bottles?: number, makeable_count?: number, party_mode?: boolean, suggested?: any } | null} */
  let summary = null
  /** @type {string | null} */
  let appUrl = null
  let loaded = false
  let unavailable = false

  onMount(async () => {
    try {
      const res = await fetch('/api/guest/bar')
      if (res.status === 503 || res.status === 502) {
        unavailable = true
        return
      }
      if (!res.ok) {
        unavailable = true
        return
      }
      const body = await res.json()
      summary = body.bar_summary ?? null
      appUrl = body.bar_app_url ?? null
    } catch {
      unavailable = true
    } finally {
      loaded = true
    }
  })
</script>

<svelte:head>
  <title>Bar — Home Hub</title>
</svelte:head>

<main class="guest-page">
  <header class="guest-header">
    <h1>The bar.</h1>
    <p class="guest-subtitle">Find something to enjoy.</p>
  </header>

  {#if !loaded}
    <section class="guest-card">
      <p class="muted">Loading…</p>
    </section>
  {:else if unavailable || !summary}
    <section class="guest-card">
      <div class="card-head"><Wine size={20} strokeWidth={1.5} /><h2>Bar</h2></div>
      <p class="muted">The bar menu is unavailable right now.</p>
    </section>
  {:else}
    <section class="guest-card">
      <div class="card-head">
        <Wine size={20} strokeWidth={1.5} />
        <h2>Behind the bar</h2>
        {#if summary.party_mode}
          <span class="chip chip-party">Party mode</span>
        {/if}
      </div>
      <div class="stats">
        <div class="stat">
          <div class="stat-value">{summary.total_bottles ?? '—'}</div>
          <div class="stat-label">Bottles</div>
        </div>
        <div class="stat">
          <div class="stat-value">{summary.makeable_count ?? '—'}</div>
          <div class="stat-label">Drinks you can make</div>
        </div>
      </div>
    </section>

    {#if summary.suggested}
      <section class="guest-card">
        <div class="card-head">
          <Sparkles size={20} strokeWidth={1.5} />
          <h2>Try this</h2>
        </div>
        <div class="suggestion-name">{summary.suggested.name ?? summary.suggested}</div>
        {#if summary.suggested.ingredients}
          <ul class="ingredients">
            {#each summary.suggested.ingredients as item}
              <li>{item}</li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    {#if appUrl}
      <a class="cta" href={appUrl} target="_blank" rel="noopener">
        Open the bar app
        <ExternalLink size={16} strokeWidth={1.75} />
      </a>
    {/if}
  {/if}
</main>

<style>
  .guest-page {
    max-width: 680px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }

  .guest-header { text-align: left; margin-bottom: 4px; padding: 4px 2px 8px; }
  .guest-header h1 {
    font-family: var(--font-display);
    font-size: clamp(38px, 7vw, 60px);
    line-height: 1;
    margin: 0 0 8px;
    letter-spacing: -0.035em;
    color: var(--guest-ink);
  }
  .guest-subtitle {
    font-size: 14px;
    color: var(--guest-muted);
    margin: 0;
  }

  .guest-card {
    background: linear-gradient(145deg,#3e3028,#262923);
    border: 1px solid var(--guest-line);
    border-radius: 20px;
    padding: clamp(17px, 4vw, 26px);
    backdrop-filter: blur(12px);
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
    color: var(--guest-ink);
  }
  .card-head h2 {
    font-family: var(--font-display);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
    color: var(--guest-ink);
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
  .chip-party {
    background: rgba(244, 114, 182, 0.18);
    color: #f472b6;
    border: 1px solid rgba(244, 114, 182, 0.4);
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
    color: var(--guest-ink);
  }
  .stat-label {
    font-size: 12px;
    color: rgba(245, 243, 238, 0.6);
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .suggestion-name {
    font-size: 22px;
    font-weight: 500;
    color: var(--guest-ink);
  }
  .ingredients {
    margin: 12px 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ingredients li {
    font-size: 14px;
    color: rgba(245, 243, 238, 0.78);
    padding-left: 14px;
    position: relative;
  }
  .ingredients li::before {
    content: '·';
    position: absolute;
    left: 4px;
    color: rgba(245, 243, 238, 0.45);
  }

  .cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 14px 20px;
    background: var(--guest-gold);
    border: 1px solid rgba(255, 255, 255, 0.18);
    border-radius: 14px;
    color: #263027;
    font-size: 15px;
    font-weight: 650;
    text-decoration: none;
    transition: background 0.15s;
  }
  .cta:hover { background: #f4dcb2; }

  .muted {
    font-size: 14px;
    color: var(--guest-muted);
    margin: 0;
  }

  @media (max-width: 480px) {
    .guest-header h1 { font-size: clamp(36px, 9vw, 44px); }
    .stat-value { font-size: 34px; }
  }
</style>
