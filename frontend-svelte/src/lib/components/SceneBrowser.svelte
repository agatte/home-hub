<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { activateScene } from '$lib/stores/init.js'
  import { SCENE_CATEGORIES } from '$lib/theme.js'

  /** @type {Array<{id: string, name: string, display_name: string, category: string, effect?: string, source: string}>} */
  let scenes = []
  /** @type {Array<{name: string, display_name: string, description?: string}>} */
  let effects = []
  /** @type {Array<{id: string, name: string, ids: string[]}>} */
  let bridgeScenes = []

  let activeTab = 'all'
  let activatingId = ''
  /** @type {string | null} */
  let activeEffect = null

  const TABS = [
    { id: 'all', label: 'All' },
    { id: 'functional', label: 'Functional' },
    { id: 'cozy', label: 'Cozy' },
    { id: 'moody', label: 'Moody' },
    { id: 'vibrant', label: 'Vibrant' },
    { id: 'nature', label: 'Nature' },
    { id: 'entertainment', label: 'Entertainment' },
    { id: 'social', label: 'Social' },
    { id: 'effects', label: 'Effects' },
    { id: 'bridge', label: 'Hue Scenes' },
  ]

  onMount(async () => {
    try {
      const resp = await apiGet('/api/scenes')
      const all = resp.scenes || []
      scenes = all.filter((s) => s.source === 'preset' || s.source === 'custom')

      // Deduplicate bridge scenes by name
      /** @type {Map<string, {id: string, name: string, ids: string[]}>} */
      const grouped = new Map()
      for (const s of all.filter((s) => s.source === 'bridge')) {
        if (!grouped.has(s.name)) {
          grouped.set(s.name, { ...s, ids: [s.id] })
        } else {
          grouped.get(s.name).ids.push(s.id)
        }
      }
      bridgeScenes = Array.from(grouped.values())
    } catch {
      /* ignore */
    }

    try {
      const data = await apiGet('/api/scenes/effects')
      effects = data.effects || []
    } catch {
      /* ignore */
    }
  })

  $: filtered = (() => {
    if (activeTab === 'all') return scenes
    if (activeTab === 'effects' || activeTab === 'bridge') return []
    return scenes.filter((s) => s.category === activeTab)
  })()

  async function activate(sceneId) {
    activatingId = sceneId
    try {
      await apiPost(`/api/scenes/${sceneId}/activate`, {})
    } catch {
      /* ignore */
    }
    setTimeout(() => { activatingId = '' }, 600)
  }

  function activateBridge(scene) {
    scene.ids.forEach((id) => activateScene(id))
  }

  async function toggleEffect(effectName) {
    const endpoint = effectName === activeEffect ? 'stop' : effectName
    try {
      await apiPost(`/api/scenes/effects/${endpoint}`)
      activeEffect = effectName === activeEffect ? null : effectName
    } catch {
      /* ignore */
    }
  }
</script>

<div class="scene-browser">
  <div class="scene-tabs">
    {#each TABS as tab}
      <button
        class="scene-tab"
        class:active={activeTab === tab.id}
        on:click={() => activeTab = tab.id}
      >
        {tab.label}
      </button>
    {/each}
  </div>

  <!-- Curated + Custom scenes -->
  {#if activeTab !== 'effects' && activeTab !== 'bridge'}
    <div class="scene-grid">
      {#each filtered as scene (scene.id)}
        {@const catMeta = SCENE_CATEGORIES[scene.category] || SCENE_CATEGORIES.custom}
        <button
          class="scene-item"
          class:activating={activatingId === scene.id}
          on:click={() => activate(scene.id)}
          title={scene.display_name}
        >
          <span class="scene-name">{scene.display_name}</span>
          {#if scene.effect}
            <span class="scene-effect-badge" style="color: {catMeta.color}">{scene.effect}</span>
          {/if}
        </button>
      {/each}
      {#if filtered.length === 0}
        <span class="scene-empty">No scenes in this category</span>
      {/if}
    </div>
  {/if}

  <!-- Effects tab -->
  {#if activeTab === 'effects'}
    <div class="scene-grid">
      {#each effects as effect}
        <button
          class="scene-item"
          class:scene-item-active={activeEffect === effect.name}
          on:click={() => toggleEffect(effect.name)}
          title={effect.description ?? ''}
        >
          <span class="scene-name">{effect.display_name}</span>
        </button>
      {/each}
      {#if effects.length === 0}
        <span class="scene-empty">No effects available (Hue v2 not connected)</span>
      {/if}
    </div>
  {/if}

  <!-- Bridge scenes tab -->
  {#if activeTab === 'bridge'}
    <div class="scene-grid">
      {#each bridgeScenes as scene}
        <button
          class="scene-item"
          on:click={() => activateBridge(scene)}
        >
          <span class="scene-name">{scene.name}</span>
        </button>
      {/each}
      {#if bridgeScenes.length === 0}
        <span class="scene-empty">No bridge scenes found</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .scene-browser {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .scene-tabs {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }

  .scene-tabs::-webkit-scrollbar {
    display: none;
  }

  .scene-tab {
    padding: 4px 10px;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
    transition: color 0.15s, background 0.15s;
  }

  .scene-tab:hover {
    color: var(--text-secondary);
  }

  .scene-tab.active {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.08);
  }

  .scene-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .scene-item {
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: transparent;
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s;
    white-space: nowrap;
  }

  .scene-item:hover {
    border-color: var(--border-hover);
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.03);
  }

  .scene-item.activating {
    border-color: var(--accent);
    color: var(--accent);
    background: rgba(74, 108, 247, 0.08);
  }

  .scene-item-active {
    border-color: var(--success);
    color: var(--success);
    background: rgba(52, 211, 153, 0.08);
  }

  .scene-name {
    font-size: 12px;
  }

  .scene-effect-badge {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    opacity: 0.7;
  }

  .scene-empty {
    font-size: 12px;
    color: var(--text-muted);
    padding: 4px 0;
  }
</style>
