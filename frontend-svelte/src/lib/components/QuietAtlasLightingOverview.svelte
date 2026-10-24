<script>
  import { lights } from '$lib/stores/lights.js'
  import { connected } from '$lib/stores/connection.js'
  import { automation, houseStateLabel, activityLabel, automationSourceLabel } from '$lib/stores/automation.js'
  import { buildLightingOverview, selectQuickScenes } from '$lib/quietAtlas/lightingModel.js'

  /** @type {Array<Record<string, any>>} */
  export let sceneList = []
  /** @type {string[]} Explicitly selected IDs; no favorites are persisted here. */
  export let favoriteSceneIds = []
  /** @type {boolean} */
  export let sceneLoading = false
  /** @type {string} */
  export let sceneError = ''
  /** @type {(id: string) => void} Parent owns safe navigation/sheet. */
  export let onOpenGroup = () => {}
  /** @type {() => void} Parent owns scene browser navigation. */
  export let onBrowseScenes = () => {}
  /** @type {(sceneId: string) => void} Parent owns existing authorized actuation. */
  export let onOpenScene = () => {}

  $: groups = buildLightingOverview($lights, $connected)
  $: quickScenes = selectQuickScenes(sceneList, favoriteSceneIds)
  $: house = houseStateLabel($automation.house_state) || 'State unavailable'
  $: activity = activityLabel($automation.activity)
  $: owner = $connected ? automationSourceLabel($automation) : 'Source unverified'
  $: dnd = $automation.dnd?.enabled === true

  const stateText = { stale: 'Connection lost', on: 'On', off: 'Off', mixed: 'Mixed', partial: 'Partially available', offline: 'Offline', unknown: 'Unavailable' }
</script>

<section class="quiet-atlas" aria-label="Home and lighting overview">
  <div class="context">
    <div class="eyebrow">HOMEHUB · {$connected ? 'CONNECTED' : 'NOT CONNECTED'}</div>
    <h1>{house}</h1>
    {#if activity}<p class="activity">{activity}</p>{/if}
    <p class="provenance">{owner}{dnd ? ' · Do Not Disturb' : ''}</p>
    {#if !$connected}<p class="connection-warning" role="status">Connection unavailable. State and lighting information may be stale. Controls are disabled in this preview.</p>{/if}
  </div>

  <div class="section-heading">
    <div>
      <div class="eyebrow">YOUR APARTMENT</div>
      <h2>Lighting</h2>
    </div>
    <span class="section-caption">Tap an area for controls</span>
  </div>

  <div class="groups">
    {#each groups as group (group.id)}
      <button
        type="button"
        class="group"
        on:click={() => onOpenGroup(group.id)}
        aria-label={`Open ${group.label} lighting controls: ${stateText[group.status]}`}
      >
        <span class="group-top"><span class="group-name">{group.label}</span><span class="chevron" aria-hidden="true">↗</span></span>
        <span class="group-status" class:available={group.status === 'on'}>
          <span class="status-dot" aria-hidden="true"></span>
          {stateText[group.status]}
          {#if $connected && group.status !== 'unknown' && group.status !== 'offline' && group.status !== 'partial'}
            <span class="count">· {group.onCount}/{group.total} on</span>
          {/if}
        </span>
      </button>
    {/each}
  </div>

  <div class="section-heading presets-heading">
    <div>
      <div class="eyebrow">SET THE ATMOSPHERE</div>
      <h2>{favoriteSceneIds.length ? 'Favorite scenes' : 'Quick scenes'}</h2>
    </div>
    <button type="button" class="browse" on:click={onBrowseScenes}>All presets ↗</button>
  </div>
  {#if sceneLoading}
    <p class="empty" role="status">Loading scene names…</p>
  {:else if sceneError}
    <p class="empty" role="alert">Scene names unavailable. Use All presets to retry.</p>
  {:else if quickScenes.length}
    <div class="scene-row">
      {#each quickScenes as scene (scene.id)}
        <button type="button" class="scene" on:click={() => onOpenScene(scene.id)}>
          <span>{scene.name}</span><span class="scene-kind">{scene.source === 'custom' ? 'Custom' : scene.source === 'bridge' ? 'Hue scene' : 'Curated'}</span>
        </button>
      {/each}
    </div>
  {:else}
    <p class="empty">No quick scenes are available. Open All presets to browse available scenes.</p>
  {/if}
</section>

<style>
  .quiet-atlas { color: #eaeae4; font-family: system-ui, -apple-system, sans-serif; width: 100%; max-width: 100%; }
  .context { background: radial-gradient(ellipse at 88% 10%, rgba(130,157,110,.17), transparent 54%), #101b18; border: 1px solid #304238; border-radius: 24px; padding: 26px 24px; }
  .eyebrow { color: #9fb3a1; font-size: 11px; font-weight: 700; letter-spacing: .14em; }
  h1, h2, p { margin: 0; }
  h1 { font-family: Georgia, serif; font-weight: 400; font-size: clamp(34px, 7vw, 54px); line-height: 1.1; margin-top: 14px; }
  .activity { margin-top: 7px; color: #e3c6a3; font-size: 18px; }
  .provenance { color: #b8c6bb; font-size: 13px; margin-top: 16px; }
  .connection-warning { color: #f0d3a0; border-top: 1px solid #776241; margin-top: 16px; padding-top: 12px; font-size: 12px; line-height: 1.5; }
  .section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; margin: 28px 0 14px; }
  h2 { font-family: Georgia, serif; font-size: 29px; font-weight: 400; margin-top: 5px; }
  .section-caption { font-size: 12px; color: #b8c6bb; text-align: right; }
  .groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  button { cursor: pointer; font: inherit; }
  button:focus-visible { outline: 3px solid #d2ebbe; outline-offset: 3px; }
  .group { min-width: 0; min-height: 111px; border: 1px solid #425449; border-radius: 18px; padding: 18px; color: #f0f2e9; text-align: left; background: linear-gradient(135deg, #1a2a23, #15221c); display: flex; flex-direction: column; justify-content: space-between; transition: border-color .15s ease, background .15s ease; }
  .group:hover { border-color: #9dbb9d; }
  .group-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  .group-name { font-weight: 600; font-size: 16px; overflow-wrap: anywhere; }
  .chevron { color: #b8c6bb; }
  .group-status { font-size: 12px; color: #d4c19f; display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }
  .group-status.available { color: #c6e1b7; }
  .status-dot { height: 6px; width: 6px; border-radius: 100%; background: currentColor; }
  .count { color: #afc2b7; }
  .presets-heading { margin-top: 30px; }
  .browse { background: transparent; color: #c9e2c0; border: none; text-decoration: underline; padding: 10px 0; min-height: 44px; font-size: 13px; }
  .scene-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .scene { color: #edece4; text-align: left; background: #243127; border: 1px solid #425449; border-radius: 14px; min-height: 76px; padding: 14px 15px; display: flex; flex-direction: column; gap: 8px; justify-content: space-between; }
  .scene-kind { font-size: 11px; color: #bac9ba; }
  .empty { border: 1px dashed #526057; border-radius: 12px; color: #bac9ba; font-size: 13px; padding: 18px; }
  @media(min-width: 900px) { .groups { grid-template-columns: repeat(4, minmax(0, 1fr)); } .scene-row { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  @media(max-width: 350px) { .context { padding: 20px 16px; } .group { padding: 13px; } .group-name { font-size: 14px; } }
  @media(prefers-reduced-motion: reduce) { .group { transition: none; } }
</style>
