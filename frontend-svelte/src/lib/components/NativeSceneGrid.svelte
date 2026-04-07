<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { activateScene } from '$lib/stores/init.js'

  /** @type {Array<{ id: string, name: string, ids: string[] }>} */
  let bridgeScenes = []
  /** @type {Array<{ name: string, display_name: string, description?: string }>} */
  let effects = []
  /** @type {string | null} */
  let activeEffect = null

  onMount(async () => {
    try {
      const data = await apiGet('/api/scenes')
      const scenes = (data.scenes || []).filter((s) => s.source === 'bridge')
      // Deduplicate by name — group scenes that exist in multiple rooms.
      /** @type {Map<string, { id: string, name: string, ids: string[] }>} */
      const grouped = new Map()
      for (const scene of scenes) {
        if (!grouped.has(scene.name)) {
          grouped.set(scene.name, { ...scene, ids: [scene.id] })
        } else {
          grouped.get(scene.name).ids.push(scene.id)
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

  /** @param {{ ids: string[] }} scene */
  function activate(scene) {
    scene.ids.forEach((id) => activateScene(id))
  }

  /** @param {string} effectName */
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

{#if bridgeScenes.length > 0 || effects.length > 0}
  <div class="native-scene-section">
    {#if bridgeScenes.length > 0}
      <h3 class="subsection-title">Hue Scenes</h3>
      <div class="scene-bar">
        {#each bridgeScenes as scene}
          <button class="scene-btn" on:click={() => activate(scene)}>
            <span class="scene-name">{scene.name}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if effects.length > 0}
      <h3 class="subsection-title">Effects</h3>
      <div class="scene-bar">
        {#each effects as effect}
          <button
            class="scene-btn"
            class:scene-btn-active={activeEffect === effect.name}
            on:click={() => toggleEffect(effect.name)}
            title={effect.description ?? ''}
          >
            <span class="scene-name">{effect.display_name}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>
{/if}
