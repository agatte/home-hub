<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { SCENE_CATEGORIES } from '$lib/theme.js'

  /** @type {Array<{id: string, name: string, display_name: string, category: string, effect?: string, source: string}>} */
  let scenes = []
  let activeTab = 'all'
  let activatingId = ''

  const TABS = [
    { id: 'all', label: 'All' },
    { id: 'functional', label: 'Functional' },
    { id: 'mood', label: 'Mood' },
    { id: 'entertainment', label: 'Entertainment' },
    { id: 'social', label: 'Social' },
    { id: 'special', label: 'Special' },
  ]

  onMount(async () => {
    try {
      const resp = await apiGet('/api/scenes')
      scenes = resp.scenes || []
    } catch {
      /* ignore */
    }
  })

  $: filtered = activeTab === 'all'
    ? scenes.filter((s) => s.source === 'preset' || s.source === 'custom')
    : scenes.filter((s) => s.category === activeTab)

  async function activate(sceneId) {
    activatingId = sceneId
    try {
      await apiPost(`/api/scenes/${sceneId}/activate`, {})
    } catch {
      /* ignore */
    }
    setTimeout(() => { activatingId = '' }, 600)
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
  </div>
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

  .scene-name {
    font-size: 12px;
  }

  .scene-effect-badge {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    opacity: 0.7;
  }
</style>
