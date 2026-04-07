<script>
  import { onMount } from 'svelte'
  import QuickActions from '$lib/components/QuickActions.svelte'
  import ModeIndicator from '$lib/components/ModeIndicator.svelte'
  import ModeOverrideBar from '$lib/components/ModeOverrideBar.svelte'
  import RoutineCard from '$lib/components/RoutineCard.svelte'
  import LightGrid from '$lib/components/LightGrid.svelte'
  import NativeSceneGrid from '$lib/components/NativeSceneGrid.svelte'
  import SceneButton from '$lib/components/SceneButton.svelte'
  import SonosCard from '$lib/components/SonosCard.svelte'
  import MusicSuggestionToast from '$lib/components/MusicSuggestionToast.svelte'
  import { apiGet } from '$lib/api.js'
  import { activateScene } from '$lib/stores/init.js'

  // SvelteKit passes data + params props to pages; declare them to silence
  // Svelte's unknown-prop warnings.
  /** @type {any} */
  export let data = undefined
  /** @type {any} */
  export let params = undefined
  data; params;

  /** @type {Array<{ id?: string, name: string, display_name: string }>} */
  let scenes = []

  onMount(async () => {
    try {
      const resp = await apiGet('/api/scenes')
      scenes = (resp.scenes || []).filter((s) => s.source === 'preset')
    } catch {
      /* ignore */
    }
  })
</script>

<main class="home-page">
  <QuickActions />

  <div class="widget-grid">
    <section class="widget widget-mode">
      <h2 class="widget-title">Mode</h2>
      <ModeIndicator />
      <ModeOverrideBar />
    </section>

    <section class="widget widget-sonos">
      <h2 class="widget-title">Sonos</h2>
      <SonosCard />
    </section>

    <section class="widget widget-lights">
      <h2 class="widget-title">Lights</h2>
      <LightGrid />
      <div class="scene-bar">
        {#each scenes as scene (scene.id || scene.name)}
          <SceneButton
            name={scene.id || scene.name}
            displayName={scene.display_name}
            onActivate={activateScene}
          />
        {/each}
      </div>
      <NativeSceneGrid />
    </section>

    <section class="widget widget-routines widget-routines-full">
      <h2 class="widget-title">Routines</h2>
      <RoutineCard />
    </section>
  </div>

  <MusicSuggestionToast />
</main>
