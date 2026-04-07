<script>
  import RecommendationCard from './RecommendationCard.svelte'
  import { apiPost } from '$lib/api.js'

  const MODES = [
    { key: 'gaming',  label: 'Gaming' },
    { key: 'working', label: 'Working' },
    { key: 'relax',   label: 'Relax' },
    { key: 'social',  label: 'Party' },
  ]

  let activeMode = 'gaming'
  /** @type {any[]} */
  let recs = []
  let loading = false
  let generating = false
  /** @type {string | null} */
  let errMsg = null

  /** @param {string} mode */
  async function fetchRecs(mode) {
    loading = true
    errMsg = null
    try {
      const res = await fetch(`/api/music/recommendations?mode=${mode}`)
      const data = await res.json()
      recs = data.recommendations || []
      if (data.message) errMsg = data.message
    } catch {
      errMsg = 'Failed to fetch recommendations'
    }
    loading = false
  }

  // Re-fetch whenever activeMode changes.
  $: fetchRecs(activeMode)

  async function handleGenerate() {
    generating = true
    errMsg = null
    try {
      const res = await fetch(`/api/music/recommendations/generate?mode=${activeMode}`, { method: 'POST' })
      if (!res.ok) {
        const data = await res.json()
        errMsg = data.detail || 'Generation failed'
      } else {
        await fetchRecs(activeMode)
      }
    } catch {
      errMsg = 'Failed to generate recommendations'
    }
    generating = false
  }

  /** @param {number} recId @param {'liked' | 'dismissed'} action */
  async function handleFeedback(recId, action) {
    try {
      await fetch(`/api/music/recommendations/${recId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
      recs = recs.filter((r) => r.id !== recId)
    } catch {
      /* ignore */
    }
  }

  /** @param {string} previewUrl */
  async function handlePreview(previewUrl) {
    try {
      await apiPost('/api/music/preview', { preview_url: previewUrl })
    } catch {
      /* ignore */
    }
  }
</script>

<div class="rec-panel">
  <div class="rec-tabs">
    {#each MODES as { key, label } (key)}
      <button
        class="rec-tab"
        class:rec-tab-active={activeMode === key}
        on:click={() => (activeMode = key)}
      >
        {label}
      </button>
    {/each}
  </div>

  <div class="rec-content">
    {#if recs.length > 0}
      <!-- Keep the list mounted during refetch so the page doesn't shrink and
           jump the scroll position. Dim it slightly while loading. -->
      <div class="rec-list" class:rec-list-loading={loading}>
        {#each recs as rec (rec.id)}
          <RecommendationCard {rec} onFeedback={handleFeedback} onPreview={handlePreview} />
        {/each}
      </div>
    {:else if loading}
      <p class="rec-loading">Loading...</p>
    {:else}
      <div class="rec-empty">
        <p>{errMsg || 'No recommendations yet for this mode.'}</p>
      </div>
    {/if}

    <button class="action-btn rec-generate-btn" on:click={handleGenerate} disabled={generating}>
      {generating ? 'Generating...' : 'Generate Recommendations'}
    </button>
  </div>
</div>
