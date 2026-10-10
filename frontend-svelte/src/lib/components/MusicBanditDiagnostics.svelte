<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'

  /** @typedef {{ title: string, period: string, alpha: number, beta: number, mean: number }} Arm */
  /** @type {{ arm_count: number, total_selections: number, top_arms: Record<string, Record<string, Arm[]>> } | null} */
  let status = null
  let loading = true
  let failed = false

  export async function refresh() {
    loading = true
    failed = false
    status = null
    try {
      const result = await apiGet('/api/music/bandit-status')
      if (!result || !result.top_arms) throw new Error('Missing bandit status')
      status = result
    } catch {
      failed = true
    } finally {
      loading = false
    }
  }

  /** @param {string} value */
  function label(value) {
    return value === 'idle' ? 'Away' : value.replaceAll('_', ' ')
  }

  onMount(() => { void refresh() })
</script>

<section class="bandit widget" aria-labelledby="bandit-heading">
  <div class="heading">
    <h2 id="bandit-heading" class="widget-title">Music Bandit diagnostics</h2>
    <button type="button" class="action-btn" on:click={refresh} disabled={loading}>
      Refresh diagnostics
    </button>
  </div>
  <p>
    The bandit helps choose among multiple mapped playlists when no explicit vibe is requested,
    using activity mode, time period, and weather. This read-only snapshot does not predict the
    next playlist: selection uses random sampling and exploration.
  </p>
  <div aria-live="polite" aria-busy={loading}>
    {#if loading}
      <p>Loading bandit diagnostics…</p>
    {:else if failed}
      <p>Bandit diagnostics unavailable. Try refreshing.</p>
    {:else if status}
      <p><strong>{status.arm_count}</strong> stored arms · <strong>{status.total_selections}</strong> recorded selections</p>
      <p>
        An arm represents a playlist in a mode, time period, and weather context.
        Selections are model choices, not confirmed plays or feedback counts.
      </p>
      {#if Object.keys(status.top_arms).length === 0}
        <p>No arm rankings reported. This endpoint cannot distinguish an unavailable bandit from an empty model.</p>
      {:else}
        <details>
          <summary>Inspect rankings and model parameters</summary>
          <p>
            Up to five arms per mode and weather group, ranked by model mean across time periods.
            These are not period-specific winners or necessarily current playlist candidates.
            Weather “any” is the weather-agnostic bucket, not current weather.
          </p>
          <p>
            Alpha and beta are posterior parameters that include starting priors and may include
            inherited weather-agnostic values. They are not observed success/failure counts.
            Mean = alpha / (alpha + beta), not measured playback success or confidence.
            Actual evidence counts and cold-start status cannot be determined from this snapshot.
          </p>
          {#each Object.entries(status.top_arms) as [mode, byWeather]}
            {#each Object.entries(byWeather) as [weather, arms]}
              <div class="ranking">
                <h3>{label(mode)} · {label(weather)}</h3>
                <ol>
                  {#each arms as arm}
                    <li>
                      <strong>{arm.title}</strong>
                      <span>Period: {label(arm.period)} · Mean: {arm.mean} · Alpha: {arm.alpha} · Beta: {arm.beta}</span>
                    </li>
                  {/each}
                </ol>
              </div>
            {/each}
          {/each}
        </details>
      {/if}
    {/if}
  </div>
</section>

<style>
  .bandit { box-sizing: border-box; width: calc(100% - 8px); max-width: 1240px; margin: 0 auto; min-width: 0; }
  .heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
  p, li { font-size: 13px; line-height: 1.6; color: var(--text-secondary); }
  p { margin: 12px 0; }
  summary { cursor: pointer; color: var(--text-primary); padding: 8px 0; }
  summary:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  .ranking { border-top: 1px solid var(--border); padding: 12px 0; overflow-wrap: anywhere; }
  h3 { margin: 0; font-size: 13px; text-transform: capitalize; }
  ol { margin: 8px 0 0; padding-left: 24px; }
  li { padding: 4px 0; }
  li strong { color: var(--text-primary); }
  li span { display: block; font-variant-numeric: tabular-nums; }
</style>
