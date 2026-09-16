<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'

  const MODES = [
    { key: 'gaming', label: 'Gaming' },
    { key: 'working', label: 'Working' },
    { key: 'relax', label: 'Relax' },
    { key: 'social', label: 'Social' },
    { key: 'gameday', label: 'Game Day' },
  ]

  const POLICIES = [
    { key: 'gentle', label: 'Gentle', detail: 'Familiarity-first' },
    { key: 'explore', label: 'Explore', detail: 'More new-to-you' },
  ]

  let activeMode = 'gaming'
  let policy = 'gentle'
  let intent = ''
  let loading = false
  let statusLoading = true
  /** @type {string | null} */
  let error = null
  /** @type {any | null} */
  let capability = null
  /** @type {any | null} */
  let result = null
  /** @type {Record<string, { action: string, state: string, clientEventId: string }>} */
  let evaluations = {}

  export async function refreshStatus() {
    try {
      capability = await apiGet('/api/music/discovery/status')
    } catch {
      capability = null
    } finally {
      statusLoading = false
    }
  }

  onMount(() => {
    void refreshStatus()
  })

  async function preview() {
    loading = true
    error = null
    result = null
    evaluations = {}
    try {
      const query = new URLSearchParams({
        mode: activeMode,
        policy,
        count: '6',
        tracks_per_artist: '3',
      })
      if (intent.trim()) query.set('intent', intent.trim())
      result = await apiPost(
        `/api/music/discovery/preview?${query}`,
        undefined,
        { timeout: 30000 },
      )
    } catch {
      error = 'Discovery preview failed'
    } finally {
      loading = false
    }
  }

  function feedbackEventId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
    return `music-feedback-${Date.now()}-${Math.random().toString(16).slice(2)}`
  }

  /** @param {any} cluster @param {string} action */
  async function evaluate(cluster, action) {
    const artist = cluster?.artist_name
    const track = cluster?.tracks?.[0]
    if (!artist || !track?.provider || !track?.provider_id) return
    const current = evaluations[artist]
    if (current?.action === action && current?.state === 'saved') return
    const clientEventId = current?.action === action && current?.clientEventId
      ? current.clientEventId
      : feedbackEventId()

    evaluations = { ...evaluations, [artist]: { action, state: 'saving', clientEventId } }
    try {
      await apiPost('/api/music/discovery/feedback', {
        client_event_id: clientEventId,
        action,
        target_kind: 'artist',
        artist_name: artist,
        provider: track.provider,
        provider_id: track.provider_id,
        mode: activeMode,
        policy,
        intent: intent.trim() || null,
      })
      evaluations = { ...evaluations, [artist]: { action, state: 'saved', clientEventId } }
    } catch {
      evaluations = { ...evaluations, [artist]: { action, state: 'error', clientEventId } }
    }
  }

  /** @param {number | null | undefined} value */
  function percent(value) {
    return value == null ? null : Math.round(Number(value) * 100)
  }

  /** @param {any} cluster */
  function artwork(cluster) {
    return cluster?.tracks?.find((track) => track.artwork_url)?.artwork_url || null
  }
</script>

<div class="discovery-lab">
  <div class="lab-header">
    <div>
      <div class="lab-kicker">Shadow only · never queues audio</div>
      <h3>Music Intelligence Preview</h3>
      <p>Try a context or mood, then inspect why HomeHub thinks each artist fits.</p>
    </div>
    <div class="capability" class:capability-off={!capability?.source_enabled}>
      {#if statusLoading}
        Checking sources…
      {:else if capability?.source_enabled}
        Last.fm source ready{capability?.semantic_enabled ? ' · semantics ready' : ''}
      {:else}
        Discovery source unavailable
      {/if}
    </div>
  </div>

  <div class="lab-controls">
    <label>
      <span>Context</span>
      <select bind:value={activeMode} aria-label="Discovery context">
        {#each MODES as mode (mode.key)}
          <option value={mode.key}>{mode.label}</option>
        {/each}
      </select>
    </label>

    <label class="intent-field">
      <span>Mood or intent <small>optional</small></span>
      <input bind:value={intent} placeholder="energetic, Valheim, dark ritual drums" />
    </label>
    <div class="policy-group" aria-label="Discovery policy">
      <span>Policy</span>
      <div class="policy-buttons">
        {#each POLICIES as item (item.key)}
          <button
            type="button"
            class:active={policy === item.key}
            on:click={() => (policy = item.key)}
            title={item.detail}
          >
            {item.label}
          </button>
        {/each}
      </div>
    </div>

    <button
      class="run-btn"
      type="button"
      on:click={preview}
      disabled={loading || statusLoading || capability?.source_enabled === false}
    >
      {loading ? 'Thinking…' : 'Preview recommendations'}
    </button>
  </div>

  {#if error}
    <div class="lab-message lab-error">{error}</div>
  {:else if result?.status === 'source_unavailable'}
    <div class="lab-message">Discovery is unavailable because the source is not configured.</div>
  {:else if result?.status === 'no_candidates'}
    <div class="lab-message">No verified candidates matched this request yet.</div>
  {/if}
  {#if result?.clusters?.length}
    <div class="result-summary">
      <span>{result.clusters.length} artist clusters</span>
      <span>{result.policy === 'explore' ? 'Exploration weighted' : 'Familiarity weighted'}</span>
      {#if result.source_cache_hit}<span>Source cache hit</span>{/if}
    </div>

    <div class="cluster-list">
      {#each result.clusters as cluster (cluster.artist_name)}
        <article class="cluster-card">
          <div class="cluster-topline">
            <div class="artist-heading">
              {#if artwork(cluster)}
                <img src={artwork(cluster)} alt="" loading="lazy" />
              {:else}
                <div class="art-placeholder" aria-hidden="true">♪</div>
              {/if}
              <div>
                <h4>{cluster.artist_name}</h4>
                <div class="chips">
                  <span>{cluster.artist_classification}</span>
                  {#if cluster.artist_depth}<span>{cluster.artist_depth} known tracks</span>{/if}
                  <span>{percent(cluster.novelty_ratio)}% new-to-you</span>
                  {#if cluster.semantic_score != null}
                    <span>{percent(cluster.semantic_score)}% semantic fit</span>
                  {/if}
                </div>
              </div>
            </div>
            <div class="score-block">
              <strong>{percent(cluster.score)}%</strong>
              <span>rank score</span>
            </div>
          </div>
          {#if cluster.semantic_intent || cluster.matched_semantics?.length}
            <div class="semantic-row">
              <span class="semantic-label">Semantic intent</span>
              <strong>{cluster.semantic_intent || activeMode}</strong>
              {#if cluster.matched_semantics?.length}
                <span class="semantic-match">matched {cluster.matched_semantics.join(', ')}</span>
              {/if}
            </div>
          {/if}

          <div class="track-grid">
            {#each cluster.tracks as track (track.provider_id)}
              <div class="track-row">
                <div>
                  <span class="track-title">{track.track_name}</span>
                  {#if track.album_name}<span class="track-album">{track.album_name}</span>{/if}
                </div>
                <span class="track-taste">{track.taste_classification}</span>
                {#if track.external_url}
                  <a href={track.external_url} target="_blank" rel="noreferrer">Open</a>
                {/if}
              </div>
            {/each}
          </div>

          <details>
            <summary>Why this ranked here</summary>
            <ul>
              {#each cluster.reasons || [] as reason}
                <li>{reason}</li>
              {/each}
            </ul>
          </details>
          <div class="evaluation-row">
            <span>Teach HomeHub</span>
            {#each [
              ['fits_me', 'Fits me'],
              ['interesting', 'Interesting'],
              ['not_for_me', 'Not for me'],
            ] as item (item[0])}
              <button
                type="button"
                class:active={evaluations[cluster.artist_name]?.action === item[0]}
                disabled={evaluations[cluster.artist_name]?.state === 'saving'}
                on:click={() => evaluate(cluster, item[0])}
              >
                {item[1]}
              </button>
            {/each}
            {#if evaluations[cluster.artist_name]?.state === 'saving'}
              <small>Saving explicit feedback…</small>
            {:else if evaluations[cluster.artist_name]?.state === 'saved'}
              <small>Saved · next preview will use this</small>
            {:else if evaluations[cluster.artist_name]?.state === 'error'}
              <small class="evaluation-error">Couldn’t save feedback</small>
            {:else}
              <small>Explicit feedback only · no playback</small>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {:else if !loading && !result}
    <div class="lab-idle">
      <strong>Nothing runs until you ask.</strong>
      <span>Pick a context, optionally describe the mood, then preview the shadow ranking.</span>
    </div>
  {/if}
</div>

<style>
  .discovery-lab {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .lab-header,
  .cluster-topline,
  .result-summary,
  .evaluation-row,
  .semantic-row {
    display: flex;
    align-items: center;
  }

  .lab-header {
    justify-content: space-between;
    gap: 20px;
  }

  .lab-header h3 {
    margin: 3px 0 4px;
    color: var(--text-primary);
    font-size: 18px;
  }

  .lab-header p,
  .lab-idle span {
    margin: 0;
    color: var(--text-secondary);
    font-size: 12px;
  }

  .lab-kicker {
    color: var(--accent);
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .capability,
  .chips span,
  .result-summary span,
  .track-taste {
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 10px;
  }

  .capability {
    padding: 6px 9px;
    white-space: nowrap;
  }

  .capability-off {
    color: var(--danger);
  }

  .lab-controls {
    display: grid;
    grid-template-columns: 150px minmax(200px, 1fr) auto auto;
    gap: 12px;
    align-items: end;
  }

  label,
  .policy-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  label > span,
  .policy-group > span {
    color: var(--text-muted);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  label small {
    text-transform: none;
    letter-spacing: 0;
  }

  select,
  input {
    min-height: 38px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
    color: var(--text-primary);
    font: inherit;
  }

  .policy-buttons {
    display: flex;
    padding: 3px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
  }

  .policy-buttons button,
  .evaluation-row button {
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
  }

  .policy-buttons button {
    padding: 7px 10px;
  }

  .policy-buttons button.active,
  .evaluation-row button.active {
    background: var(--accent);
    color: var(--bg-primary);
  }

  .run-btn {
    min-height: 38px;
    padding: 8px 14px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
    font-weight: 600;
    cursor: pointer;
  }

  .run-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .lab-message,
  .lab-idle {
    padding: 18px;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    text-align: center;
  }

  .lab-idle {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .lab-error {
    color: var(--danger);
  }

  .result-summary {
    gap: 7px;
    flex-wrap: wrap;
  }

  .result-summary span,
  .chips span,
  .track-taste {
    padding: 4px 7px;
  }

  .cluster-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .cluster-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
  }

  .cluster-topline {
    justify-content: space-between;
    gap: 14px;
  }

  .artist-heading {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  .artist-heading img,
  .art-placeholder {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    flex-shrink: 0;
  }

  .artist-heading img {
    object-fit: cover;
  }

  .art-placeholder {
    display: grid;
    place-items: center;
    background: var(--bg-card);
    color: var(--text-muted);
  }

  .artist-heading h4 {
    margin: 0 0 5px;
    color: var(--text-primary);
    font-size: 14px;
  }

  .chips {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
  }

  .score-block {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    flex-shrink: 0;
  }

  .score-block strong {
    color: var(--accent);
    font-size: 18px;
  }

  .score-block span {
    color: var(--text-muted);
    font-size: 9px;
    text-transform: uppercase;
  }

  .semantic-row {
    gap: 7px;
    flex-wrap: wrap;
    font-size: 11px;
  }

  .semantic-label,
  .semantic-match {
    color: var(--text-muted);
  }

  .semantic-row strong {
    color: var(--text-primary);
  }

  .track-grid {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .track-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 8px;
    align-items: center;
    padding: 7px 8px;
    border-radius: 8px;
    background: var(--bg-card);
  }

  .track-row > div {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .track-title {
    color: var(--text-primary);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .track-album {
    color: var(--text-muted);
    font-size: 9px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .track-row a {
    color: var(--accent);
    font-size: 10px;
    text-decoration: none;
  }

  details {
    color: var(--text-secondary);
    font-size: 10px;
  }

  summary {
    cursor: pointer;
    color: var(--text-muted);
  }

  details ul {
    margin: 7px 0 0;
    padding-left: 18px;
  }

  details li + li {
    margin-top: 3px;
  }

  .evaluation-row {
    gap: 6px;
    flex-wrap: wrap;
    padding-top: 2px;
  }

  .evaluation-row > span {
    color: var(--text-muted);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .evaluation-row button {
    padding: 5px 8px;
    border: 1px solid var(--border);
    font-size: 10px;
  }

  .evaluation-row small {
    color: var(--text-muted);
    font-size: 9px;
    margin-left: auto;
  }

  @media (max-width: 1050px) {
    .lab-controls {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .run-btn {
      width: 100%;
    }
  }

  @media (max-width: 760px) {
    .lab-header,
    .cluster-topline {
      align-items: flex-start;
      flex-direction: column;
    }

    .capability {
      white-space: normal;
    }

    .lab-controls,
    .cluster-list {
      grid-template-columns: minmax(0, 1fr);
    }

    .score-block {
      align-items: flex-start;
    }

    .track-row {
      grid-template-columns: minmax(0, 1fr) auto;
    }

    .track-row a {
      grid-column: 1 / -1;
    }

    .evaluation-row small {
      width: 100%;
      margin-left: 0;
    }
  }
</style>
