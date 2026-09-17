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
  let runKind = null
  let statusLoading = true
  /** @type {string | null} */
  let error = null
  /** @type {any | null} */
  let capability = null
  /** @type {any | null} */
  let liveCapability = null
  /** @type {any | null} */
  let liveContext = null
  /** @type {string | null} */
  let liveStatus = null
  /** @type {any | null} */
  let requestResolution = null
  /** @type {string | null} */
  let requestStatus = null
  /** @type {any[]} */
  let familiarSuggestions = []
  /** @type {any | null} */
  let result = null
  let feedbackMode = activeMode
  let feedbackPolicy = policy
  /** @type {string | null} */
  let feedbackIntent = null
  /** @type {Record<string, { action: string, state: string, clientEventId: string }>} */
  let evaluations = {}
  /** @type {Record<string, { action: string, state: string, clientEventId: string }>} */
  let trustUpdates = {}

  export async function refreshStatus() {
    const [discoveryStatus, currentContext] = await Promise.all([
      apiGet('/api/music/discovery/status').catch(() => null),
      apiGet('/api/music/live-context/status').catch(() => null),
    ])
    capability = discoveryStatus
    liveCapability = currentContext
    statusLoading = false
  }

  onMount(() => {
    void refreshStatus()
  })

  async function preview() {
    loading = true
    runKind = 'manual'
    error = null
    result = null
    liveContext = null
    liveStatus = null
    requestResolution = null
    requestStatus = null
    familiarSuggestions = []
    evaluations = {}
    trustUpdates = {}
    feedbackMode = activeMode
    feedbackPolicy = policy
    feedbackIntent = intent.trim() || null
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
      runKind = null
    }
  }

  async function previewLive() {
    loading = true
    runKind = 'live'
    error = null
    result = null
    liveContext = null
    liveStatus = null
    requestResolution = null
    requestStatus = null
    familiarSuggestions = []
    evaluations = {}
    trustUpdates = {}
    try {
      const query = new URLSearchParams({ policy, count: '6', tracks_per_artist: '3' })
      const payload = await apiPost(`/api/music/live-context/preview?${query}`, undefined, { timeout: 30000 })
      liveStatus = payload?.status || null
      liveContext = payload?.live_context || null
      result = payload?.discovery || null
      feedbackMode = liveContext?.consumer || activeMode
      feedbackPolicy = policy
      feedbackIntent = liveContext?.semantic_request || null
    } catch {
      error = 'Live-context discovery preview failed'
    } finally {
      loading = false
      runKind = null
    }
  }

  /** @param {string} requestText */
  async function previewRequest(requestText) {
    loading = true
    runKind = 'request'
    error = null
    result = null
    liveContext = null
    liveStatus = null
    requestResolution = null
    requestStatus = null
    familiarSuggestions = []
    evaluations = {}
    trustUpdates = {}
    try {
      const payload = await apiPost('/api/music/request/preview', {
        request: requestText,
        mode: activeMode,
        count: 6,
        tracks_per_artist: 3,
      }, { timeout: 30000 })
      requestStatus = payload?.status || null
      requestResolution = payload?.resolved_request || null
      familiarSuggestions = payload?.familiar_suggestions || []
      result = payload?.discovery || null
      feedbackMode = requestResolution?.mode || activeMode
      feedbackPolicy = requestResolution?.policy || policy
      feedbackIntent = requestResolution?.semantic_request || null
    } catch {
      error = 'Music request preview failed'
    } finally {
      loading = false
      runKind = null
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
        mode: feedbackMode,
        policy: feedbackPolicy,
        intent: feedbackIntent,
      })
      evaluations = { ...evaluations, [artist]: { action, state: 'saved', clientEventId } }
    } catch {
      evaluations = { ...evaluations, [artist]: { action, state: 'error', clientEventId } }
    }
  }

  function trustEventId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
    return `music-trust-${Date.now()}-${Math.random().toString(16).slice(2)}`
  }

  /** @param {any} suggestion */
  function trustKey(suggestion) {
    const candidate = suggestion?.candidate
    return candidate?.provider && candidate?.provider_id
      ? `${candidate.provider}:${candidate.provider_id}`
      : ''
  }

  /** @param {any} suggestion @param {'approve' | 'revoke'} action */
  async function updateTrust(suggestion, action) {
    const candidate = suggestion?.candidate
    const key = trustKey(suggestion)
    if (!key || !candidate?.playback_capable) return
    const current = trustUpdates[key]
    if (current?.action === action && current?.state === 'saved') return
    const clientEventId = current?.action === action && current?.clientEventId
      ? current.clientEventId
      : trustEventId()

    trustUpdates = { ...trustUpdates, [key]: { action, state: 'saving', clientEventId } }
    try {
      const payload = await apiPost('/api/music/trust/approval', {
        client_event_id: clientEventId,
        action,
        provider: candidate.provider,
        provider_id: candidate.provider_id,
      })
      familiarSuggestions = familiarSuggestions.map((item) => (
        trustKey(item) === key ? { ...item, trust: payload?.trust || item.trust } : item
      ))
      trustUpdates = { ...trustUpdates, [key]: { action, state: 'saved', clientEventId } }
    } catch {
      trustUpdates = { ...trustUpdates, [key]: { action, state: 'error', clientEventId } }
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
      <div class="lab-kicker">Music Intelligence</div>
      <h3>Find something that fits.</h3>
      <p>Tell HomeHub what you want to hear, or start with a quick pick.</p>
    </div>
  </div>

  <div class="lab-controls primary-controls">
    <label class="intent-field">
      <span>What are you in the mood for?</span>
      <input bind:value={intent} placeholder="Something familiar, new music, energetic rock…" />
    </label>
    <button class="run-btn" type="button" on:click={preview}
      disabled={loading || statusLoading || capability?.source_enabled === false}>
      {loading && runKind === 'manual' ? 'Thinking…' : 'Find recommendations'}
    </button>
  </div>

  <div class="request-presets" aria-label="Quick music requests">
    <div class="request-presets-copy">
      <span>Quick picks</span>
      <small>Start with a familiar direction, deliberate discovery, or a mood.</small>
    </div>
    <button type="button" on:click={() => previewRequest('play something familiar')} disabled={loading || statusLoading}>
      {loading && runKind === 'request' ? 'Thinking…' : 'Familiar'}
    </button>
    <button type="button" on:click={() => previewRequest('play new music')} disabled={loading || statusLoading}>New music</button>
    <button type="button" on:click={() => previewRequest("I'm feeling energetic")} disabled={loading || statusLoading}>Energetic</button>
  </div>

  <details class="advanced-controls">
    <summary>Adjust context</summary>
    <div class="advanced-grid">
      <label>
        <span>Context</span>
        <select bind:value={activeMode} aria-label="Discovery context">
          {#each MODES as mode (mode.key)}
            <option value={mode.key}>{mode.label}</option>
          {/each}
        </select>
      </label>
      <div class="policy-group" aria-label="Discovery policy">
        <span>Discovery style</span>
        <div class="policy-buttons">
          {#each POLICIES as item (item.key)}
            <button type="button" class:active={policy === item.key} on:click={() => (policy = item.key)} title={item.detail}>
              {item.label}
            </button>
          {/each}
        </div>
      </div>
      <button class="live-run-btn" type="button" on:click={previewLive} disabled={loading || statusLoading || capability?.source_enabled === false}
        title={liveCapability?.semantic_reason || 'Checks HomeHub for a trusted current music context'}>
        {loading && runKind === 'live' ? 'Reading HomeHub…' : 'Use current HomeHub context'}
      </button>
    </div>
    <details class="source-details">
      <summary>Source details</summary>
      <div class="source-status" class:capability-off={!capability?.source_enabled}>
        {#if statusLoading}Checking sources…{:else if capability?.source_enabled}Last.fm source ready{capability?.semantic_enabled ? ' · semantics ready' : ''}{:else}Discovery source unavailable{/if}
        {#if !statusLoading && liveCapability?.status === 'active'}<span>Live: {liveCapability.consumer}{liveCapability.semantic_request ? ` · ${liveCapability.semantic_request}` : ''}</span>{:else if !statusLoading}<span>No live music context active</span>{/if}
      </div>
    </details>
  </details>

  {#if liveContext}
    <div class="live-context-banner">
      <strong>Live {liveContext.consumer}</strong>
      {#if liveContext.semantic_request}<span>{liveContext.semantic_request}</span>{/if}
      {#if liveContext.semantic_reason}<span>{liveContext.semantic_reason}</span>{/if}
    </div>
  {/if}

  {#if requestResolution}
    <div class="request-resolution-banner">
      <strong>{requestResolution.kind}</strong>
      <span>{requestResolution.rationale}</span>
      <span>{percent(requestResolution.familiarity_target)}% familiar target · {percent(requestResolution.novelty_target)}% novelty target</span>
      {#if requestResolution.semantic_key}<span>semantic: {requestResolution.semantic_key}</span>{/if}
    </div>
  {/if}

  {#if familiarSuggestions.length || result?.clusters?.length}
    <div class="recommendations-heading">Recommendations</div>
  {/if}

  {#if familiarSuggestions.length}
    <div class="familiar-list">
      {#each familiarSuggestions as suggestion (suggestion.candidate.provider_id)}
        <article class="familiar-card">
          <div>
            <span class="familiar-kicker">Known favorite</span>
            <h4>{suggestion.candidate.title}</h4>
            <div class="chips">
              <span>{suggestion.taste_classification}</span>
              <span>{percent(suggestion.score)}% request fit</span>
              {#if suggestion.trust?.state}<span>{suggestion.trust.state.replace('_', ' ')}</span>{/if}
            </div>
          </div>
          {#if suggestion.trust}
            <div class="trust-row">
              <div>
                <strong>{suggestion.trust.playback_eligible ? 'Approved for future playback' : 'Suggestion only'}</strong>
                <span>
                  {suggestion.trust.playback_eligible
                    ? 'This page still does not start audio'
                    : 'Approve this favorite if you want it eligible later'}
                </span>
              </div>
              {#if suggestion.trust.explicit_approval}
                <button
                  type="button"
                  disabled={trustUpdates[trustKey(suggestion)]?.state === 'saving'}
                  on:click={() => updateTrust(suggestion, 'revoke')}
                >Revoke approval</button>
              {:else if suggestion.trust.state === 'suggestion_only' && suggestion.candidate?.playback_capable}
                <button
                  type="button"
                  disabled={trustUpdates[trustKey(suggestion)]?.state === 'saving'}
                  on:click={() => updateTrust(suggestion, 'approve')}
                >Approve for future playback</button>
              {/if}
            </div>
            {#if trustUpdates[trustKey(suggestion)]?.state === 'saving'}
              <small class="trust-status">Saving approval…</small>
            {:else if trustUpdates[trustKey(suggestion)]?.state === 'saved'}
              <small class="trust-status">Saved · trust policy updated</small>
            {:else if trustUpdates[trustKey(suggestion)]?.state === 'error'}
              <small class="trust-status trust-error">Couldn’t save approval</small>
            {/if}
            <details>
              <summary>Why HomeHub chose this</summary>
              <ul>
                {#each suggestion.trust.reasons || [] as reason}
                  <li>{reason}</li>
                {/each}
              </ul>
            </details>
          {/if}
          <details>
            <summary>Familiarity details</summary>
            <ul>
              {#each suggestion.reasons || [] as reason}
                <li>{reason}</li>
              {/each}
            </ul>
          </details>
        </article>
      {/each}
    </div>
  {/if}

  {#if error}
    <div class="lab-message lab-error">{error}</div>
  {:else if result?.status === 'source_unavailable'}
    <div class="lab-message">Discovery is unavailable because the source is not configured.</div>
  {:else if result?.status === 'no_candidates'}
    <div class="lab-message">No verified candidates matched this request yet.</div>
  {:else if liveStatus === 'inactive'}
    <div class="lab-message">No Game Day, Social, or Gaming context is active right now.</div>
  {:else if liveStatus === 'suppressed'}
    <div class="lab-message">Live music context is currently suppressed by HomeHub safety state.</div>
  {:else if requestStatus === 'no_candidates' && !familiarSuggestions.length && !result}
    <div class="lab-message">HomeHub does not have enough verified evidence to satisfy this request yet.</div>
  {:else if requestStatus === 'source_unavailable' && !familiarSuggestions.length}
    <div class="lab-message">The discovery source is unavailable for this request.</div>
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
                <span class="track-capability">
                  {track.playback_capability === 'supported' ? 'Playback ready' : 'Catalog verified · metadata only'}
                </span>
                {#if track.playback_capability !== 'supported'}
                  <span class="track-trust">Suggestion only</span>
                {/if}
                {#if track.external_url}
                  <a href={track.external_url} target="_blank" rel="noreferrer">Open</a>
                {/if}
              </div>
            {/each}
          </div>

          <details>
            <summary>Why HomeHub chose this</summary>
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
              <small>Saved</small>
            {:else if evaluations[cluster.artist_name]?.state === 'error'}
              <small class="evaluation-error">Couldn’t save feedback</small>
            {:else}
              <small>Helps future recommendations</small>
            {/if}
          </div>
        </article>
      {/each}
    </div>
  {:else if !loading && !result && !familiarSuggestions.length && !requestStatus}
    <div class="lab-idle">
      <strong>Start with a request above.</strong>
      <span>HomeHub will suggest music and explain why. Nothing here starts audio yet.</span>
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

  .live-context-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 9px 11px;
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-secondary);
    font-size: 11px;
  }
  .live-context-banner strong { color: var(--text-primary); }

  .request-resolution-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 9px 11px;
    border: 1px solid var(--border);
    border-radius: 10px;
    color: var(--text-secondary);
    font-size: 11px;
  }
  .request-resolution-banner strong { color: var(--text-primary); text-transform: capitalize; }

  .request-presets {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    padding: 9px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
  }
  .request-presets-copy { display: flex; flex-direction: column; margin-right: auto; }
  .request-presets-copy span { color: var(--text-primary); font-size: 11px; font-weight: 600; }
  .request-presets-copy small { color: var(--text-muted); font-size: 9px; }
  .request-presets button {
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-card);
    color: var(--text-secondary);
    cursor: pointer;
  }
  .request-presets button:disabled { opacity: 0.45; cursor: not-allowed; }

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

  .chips span,
  .result-summary span,
  .track-taste {
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-size: 10px;
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

  .run-btn,
  .live-run-btn {
    min-height: 38px;
    padding: 8px 14px;
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--accent) 14%, transparent);
    color: var(--accent);
    font-weight: 600;
    cursor: pointer;
  }

  .run-btn:disabled,
  .live-run-btn:disabled {
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

  .familiar-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .familiar-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
  }
  .familiar-card h4 { margin: 2px 0 6px; color: var(--text-primary); font-size: 13px; }
  .familiar-kicker { color: var(--accent); font-size: 9px; text-transform: uppercase; letter-spacing: 0.05em; }

  .trust-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 9px 10px;
    border: 1px solid var(--border);
    border-radius: 9px;
    background: var(--bg-card);
  }
  .trust-row > div { display: flex; flex-direction: column; gap: 2px; }
  .trust-row strong { color: var(--text-primary); font-size: 11px; }
  .trust-row span, .trust-status { color: var(--text-muted); font-size: 9px; }
  .trust-row button {
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    cursor: pointer;
    white-space: nowrap;
  }
  .trust-row button:disabled { opacity: 0.45; cursor: not-allowed; }
  .trust-error { color: var(--danger); }

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
    grid-template-columns: minmax(0, 1fr) auto auto auto auto;
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

  .track-capability,
  .track-trust {
    color: var(--text-muted);
    font-size: 9px;
    white-space: nowrap;
  }

  .track-trust {
    color: var(--accent);
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

    .lab-controls,
    .cluster-list,
    .familiar-list {
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


  /* #269 consumer-facing composition: diagnostics recede until requested. */
  .discovery-lab {
    max-width: 1240px;
    margin: 0 auto;
    gap: 18px;
    padding: 18px 4px 6px;
  }

  .lab-header { align-items: flex-start; padding: 0 4px; }
  .lab-header h3 { font-size: clamp(26px, 3vw, 38px); letter-spacing: -0.035em; }
  .lab-header p { max-width: 700px; font-size: 13px; line-height: 1.55; }

  .primary-controls {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: color-mix(in srgb, var(--bg-card) 94%, transparent);
  }

  .primary-controls .intent-field { min-width: 0; }
  .primary-controls .intent-field > span { color: var(--text-muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
  .primary-controls input { min-height: 46px; font-size: 13px; }
  .primary-controls .run-btn { align-self: end; min-height: 46px; min-width: 128px; }

  .request-presets {
    border: 0;
    background: transparent;
    padding: 0 4px;
  }
  .request-presets-copy small { display: none; }
  .request-presets-copy span { color: var(--text-muted); text-transform: uppercase; letter-spacing: .08em; font-size: 9px; }

  .advanced-controls {
    margin: -6px 4px 0;
    border-top: 1px solid var(--border);
    padding-top: 10px;
  }
  .advanced-controls > summary { color: var(--text-muted); cursor: pointer; font-size: 10px; list-style: none; }
  .advanced-controls > summary::-webkit-details-marker { display: none; }
  .advanced-controls > summary::after { content: '  +'; }
  .advanced-controls[open] > summary::after { content: '  −'; }
  .advanced-grid { display: grid; grid-template-columns: minmax(180px, .7fr) minmax(240px, 1fr) auto; gap: 12px; align-items: end; margin-top: 10px; }
  .advanced-grid label, .advanced-grid .policy-group { display: flex; flex-direction: column; gap: 5px; }
  .advanced-grid label > span, .advanced-grid .policy-group > span { color: var(--text-muted); font-size: 9px; text-transform: uppercase; letter-spacing: .08em; }
  .advanced-grid select { min-height: 36px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); color: var(--text-primary); padding: 0 9px; }
  .source-details { margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--border); }
  .source-details > summary { width: fit-content; color: var(--text-muted); cursor: pointer; }
  .source-status { display: flex; flex-direction: column; gap: 3px; margin-top: 7px; color: var(--text-muted); font-size: 9px; }
  .recommendations-heading { margin: 18px 4px 8px; color: var(--text-muted); font-size: 9px; font-weight: 600; letter-spacing: .1em; text-transform: uppercase; }

  .result-summary, .semantic-row, .score-block, .track-taste, .track-capability, .track-trust { display: none; }
  .request-resolution-banner { display: none; }
  .live-context-banner { display: none; }

  .cluster-list, .familiar-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .cluster-card, .familiar-card { min-width: 0; padding: 15px; border-radius: 14px; }
  .cluster-topline { align-items: flex-start; }
  .artist-heading h4, .familiar-card h4 { font-size: 17px; }
  .artist-heading .chips, .familiar-card .chips { display: none; }
  .track-grid { margin-top: 12px; border-top: 1px solid var(--border); }
  .track-row { min-height: 42px; padding: 7px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
  .track-row a { margin-left: auto; }
  .evaluation-row { margin-top: 10px; padding-top: 10px; border-top: 0; flex-wrap: wrap; }
  .evaluation-row > span { color: var(--text-muted); font-size: 9px; }
  .evaluation-row small { width: 100%; margin-top: 3px; }
  .cluster-card details, .familiar-card details { margin-top: 8px; }

  .lab-idle { min-height: 100px; border-radius: 14px; }

  @media (max-width: 900px) {
    .primary-controls, .advanced-grid, .cluster-list, .familiar-list { grid-template-columns: minmax(0, 1fr); }
    .primary-controls .run-btn { width: 100%; }
  }

</style>
