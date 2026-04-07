<script>
  import { onMount } from 'svelte'
  import GenreDonut from './GenreDonut.svelte'

  /** @type {any | null} */
  let profile = null
  let importing = false
  /** @type {any | null} */
  let importResult = null
  /** @type {HTMLInputElement | null} */
  let fileEl = null
  /** @type {HTMLInputElement | null} */
  let fileElReimport = null

  async function fetchProfile() {
    try {
      const res = await fetch('/api/music/profile')
      const data = await res.json()
      if (data.profile) profile = data.profile
    } catch {
      /* ignore */
    }
  }

  onMount(fetchProfile)

  /** @param {Event} e */
  async function handleImport(e) {
    const input = /** @type {HTMLInputElement} */ (e.target)
    const file = input.files?.[0]
    if (!file) return

    importing = true
    importResult = null

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/music/import', { method: 'POST', body: formData })
      if (!res.ok) {
        const err = await res.json()
        importResult = { error: err.detail || 'Import failed' }
      } else {
        importResult = await res.json()
        await fetchProfile()
      }
    } catch {
      importResult = { error: 'Network error during import' }
    }

    importing = false
    // Reset file inputs so re-uploading the same file works
    if (fileEl) fileEl.value = ''
    if (fileElReimport) fileElReimport.value = ''
  }
</script>

<div class="taste-profile-card">
  {#if !profile}
    <div class="taste-profile-empty">
      <div class="taste-profile-empty-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17 8 12 3 7 8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </div>
      <p class="taste-profile-empty-text">Import your Apple Music library to build a taste profile</p>
      <p class="taste-profile-empty-hint">In iTunes: File &gt; Library &gt; Export Library</p>
      <label class="action-btn taste-profile-import-btn" class:importing>
        {importing ? 'Importing...' : 'Import Library XML'}
        <input bind:this={fileEl} type="file" accept=".xml" on:change={handleImport} disabled={importing} hidden />
      </label>
      {#if importResult?.error}
        <p class="taste-profile-error">{importResult.error}</p>
      {/if}
    </div>
  {:else}
    <div class="taste-profile-header">
      <div class="taste-profile-stats">
        <div class="taste-profile-stat">
          <span class="taste-profile-stat-value">{profile.import_track_count.toLocaleString()}</span>
          <span class="taste-profile-stat-label">tracks</span>
        </div>
        <div class="taste-profile-stat">
          <span class="taste-profile-stat-value">{profile.import_artist_count.toLocaleString()}</span>
          <span class="taste-profile-stat-label">artists</span>
        </div>
        <div class="taste-profile-stat">
          <span class="taste-profile-stat-value">{Object.keys(profile.genre_distribution).length}</span>
          <span class="taste-profile-stat-label">genres</span>
        </div>
      </div>
      <label class="action-btn taste-profile-reimport" class:importing>
        {importing ? 'Importing...' : 'Re-import'}
        <input bind:this={fileElReimport} type="file" accept=".xml" on:change={handleImport} disabled={importing} hidden />
      </label>
    </div>

    <GenreDonut distribution={profile.genre_distribution} />

    {#if profile.top_artists && profile.top_artists.length > 0}
      <div class="taste-profile-top-artists">
        <h4 class="subsection-title">Top Artists</h4>
        <div class="top-artists-list">
          {#each profile.top_artists.slice(0, 8) as artist, i (artist.name)}
            <div class="top-artist-row">
              <span class="top-artist-rank">{i + 1}</span>
              <span class="top-artist-name">{artist.name}</span>
              <span class="top-artist-plays">{artist.play_count} plays</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    {#if importResult && !importResult.error}
      <p class="taste-profile-success">
        Imported {importResult.track_count} tracks from {importResult.artist_count} artists
      </p>
    {/if}
    {#if importResult?.error}
      <p class="taste-profile-error">{importResult.error}</p>
    {/if}
  {/if}
</div>
