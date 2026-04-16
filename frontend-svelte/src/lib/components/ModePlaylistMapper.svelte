<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiGet, apiPost, apiDelete } from '$lib/api.js'

  const MODE_CONFIG = [
    { mode: 'gaming',   label: 'Gaming',   icon: '🎮' },
    { mode: 'working',  label: 'Working',  icon: '💻' },
    { mode: 'watching', label: 'Watching', icon: '🎬' },
    { mode: 'relax',    label: 'Relax',    icon: '🛋️' },
    { mode: 'social',   label: 'Party',    icon: '🎉' },
    { mode: 'cooking',  label: 'Cooking',  icon: '🍳' },
  ]

  const VIBES = [
    { value: '',           label: 'No vibe tag' },
    { value: 'energetic',  label: '⚡ Energetic' },
    { value: 'focus',      label: '🎯 Focus' },
    { value: 'mellow',     label: '🌙 Mellow' },
    { value: 'background', label: '🎧 Background' },
    { value: 'hype',       label: '🔥 Hype' },
  ]

  /** @type {Record<string, any[]>} */
  let mappings = {}
  /** @type {Array<{ title: string, uri: string, source: string }>} */
  let favorites = []
  let mounted = true

  // A favorite with an empty `uri` is an Apple Music artist/station shortcut
  // (or Sonos-curated container). The Sonos backend can't auto-play these
  // because there's no static playable URI — the Sonos app resolves them on
  // tap via the music service's wire protocol, which the home-hub doesn't
  // implement. Surface this to the user instead of letting them pick a
  // favorite that will silently fail.
  /** @param {string} title */
  function isUnsupported(title) {
    const fav = favorites.find((f) => f.title === title)
    return !!fav && !fav.uri
  }

  let refreshing = false

  async function loadData() {
    try {
      const data = await apiGet('/api/music/mode-playlists')
      if (mounted) {
        mappings = data.mappings || {}
        favorites = data.favorites || []
      }
    } catch {
      /* ignore */
    }
  }

  async function refreshFavorites() {
    refreshing = true
    try {
      await apiPost('/api/sonos/favorites/refresh')
      await loadData()
    } catch {
      /* ignore */
    }
    refreshing = false
  }

  onMount(loadData)

  onDestroy(() => { mounted = false })

  // Per-mode add-row state. Keyed by mode.
  /** @type {Record<string, { title: string, vibe: string, autoPlay: boolean, saving: boolean }>} */
  let addRowState = Object.fromEntries(
    MODE_CONFIG.map(({ mode }) => [mode, { title: '', vibe: '', autoPlay: false, saving: false }])
  )

  /** @param {string} mode */
  async function handleAdd(mode) {
    const row = addRowState[mode]
    if (!row.title) return
    row.saving = true
    addRowState = { ...addRowState }
    try {
      const data = await apiPost('/api/music/mode-playlists', {
        mode,
        favorite_title: row.title,
        vibe: row.vibe || null,
        auto_play: row.autoPlay,
      })
      mappings = {
        ...mappings,
        [mode]: [
          ...(mappings[mode] || []),
          {
            id: data.id,
            mode,
            favorite_title: row.title,
            vibe: row.vibe || null,
            auto_play: row.autoPlay,
            priority: 0,
          },
        ],
      }
      addRowState[mode] = { title: '', vibe: '', autoPlay: false, saving: false }
      addRowState = { ...addRowState }
    } catch {
      row.saving = false
      addRowState = { ...addRowState }
    }
  }

  /** @param {string} mode @param {number} mappingId */
  async function handleRemove(mode, mappingId) {
    try {
      await apiDelete(`/api/music/mode-playlists/${mappingId}`)
      mappings = {
        ...mappings,
        [mode]: (mappings[mode] || []).filter((e) => e.id !== mappingId),
      }
    } catch {
      /* ignore */
    }
  }

  /** @param {string} vibe */
  function vibeLabel(vibe) {
    return VIBES.find((v) => v.value === (vibe || ''))?.label ?? vibe
  }
</script>

<div class="mode-playlist-mapper">
  <button class="refresh-btn" on:click={refreshFavorites} disabled={refreshing} title="Refresh Sonos favorites">
    {refreshing ? '↻' : '↻'} Refresh favorites
  </button>
  {#each MODE_CONFIG as { mode, label, icon } (mode)}
    {@const entries = mappings[mode] || []}
    <div class="mode-playlist-row">
      <div class="mode-playlist-mode">
        <span class="mode-playlist-icon">{icon}</span>
        <span class="mode-playlist-label">{label}</span>
      </div>
      <div class="mode-playlist-entries">
        {#each entries as entry (entry.id)}
          {@const broken = isUnsupported(entry.favorite_title)}
          <div class="mode-playlist-entry" class:entry-broken={broken}>
            <span class="entry-title">{entry.favorite_title}</span>
            {#if broken}
              <span
                class="entry-warning"
                title="This favorite is an Apple Music artist or station shortcut. The Sonos app can play it but Home Hub can't auto-play it. Remove this mapping and pick a playlist or album favorite instead."
              >⚠ unsupported</span>
            {/if}
            {#if entry.vibe}
              <span class="entry-vibe">{vibeLabel(entry.vibe)}</span>
            {/if}
            <span class="entry-auto" class:auto-on={entry.auto_play} class:auto-off={!entry.auto_play}>
              {entry.auto_play ? 'Auto' : 'Manual'}
            </span>
            <button class="icon-btn remove-btn" on:click={() => handleRemove(mode, entry.id)} title="Remove">×</button>
          </div>
        {/each}
        {#if favorites.length > 0}
          <div class="mode-playlist-add-row">
            <select
              class="setting-select mode-playlist-select"
              bind:value={addRowState[mode].title}
            >
              <option value="">Add favorite…</option>
              {#each favorites as fav (fav.title)}
                <option value={fav.title} disabled={!fav.uri}>
                  {fav.title}{!fav.uri ? ' — unsupported' : ''}
                </option>
              {/each}
            </select>
            <select
              class="setting-select vibe-select"
              bind:value={addRowState[mode].vibe}
              disabled={!addRowState[mode].title}
            >
              {#each VIBES as v (v.value)}
                <option value={v.value}>{v.label}</option>
              {/each}
            </select>
            <button
              class="toggle-btn"
              class:toggle-on={addRowState[mode].autoPlay}
              on:click={() => { addRowState[mode].autoPlay = !addRowState[mode].autoPlay; addRowState = { ...addRowState } }}
              disabled={!addRowState[mode].title}
              title={addRowState[mode].autoPlay ? 'Auto-play on mode change' : 'Manual play only'}
            >
              {addRowState[mode].autoPlay ? 'Auto' : 'Manual'}
            </button>
            <button
              class="icon-btn add-btn"
              on:click={() => handleAdd(mode)}
              disabled={!addRowState[mode].title || addRowState[mode].saving}
              title="Add mapping"
            >
              +
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/each}
  {#if favorites.length === 0}
    <p class="mode-playlist-hint">
      No Sonos favorites found. Add playlists in the Sonos app, then map them here.
    </p>
  {/if}
</div>
