<script>
  /** @typedef {{id: any, source: string, name?: string, display_name?: string}} Scene */

  /** @type {Scene[]} */
  export let scenes = []
  /** @type {Scene | null} */
  export let selected = null
  /** @type {(scene: Scene) => void} */
  export let onPick = () => {}
  /** @type {() => void} */
  export let onClear = () => {}

  export let label = 'Default'
  export let placeholder = 'Default'

  let open = false

  /** @param {MouseEvent} _e */
  function toggleOpen(_e) {
    open = !open
  }

  function pickDefault() {
    onClear()
    open = false
  }

  /** @param {Scene} scene */
  function pickScene(scene) {
    onPick(scene)
    open = false
  }

  /** @param {KeyboardEvent} e */
  function onKey(e) {
    if (e.key === 'Escape') open = false
  }
</script>

<svelte:window on:keydown={onKey} />

<div class="scene-picker" class:open>
  <button
    type="button"
    class="picker-trigger"
    class:active={!!selected}
    on:click={toggleOpen}
  >
    <span class="picker-label">{selected?.name || placeholder}</span>
    <span class="picker-chevron">▾</span>
  </button>
  {#if open}
    <div class="picker-menu">
      <button class="picker-item picker-default" on:click={pickDefault}>
        {label}
      </button>
      {#each scenes as scene (scene.id)}
        <button class="picker-item" on:click={() => pickScene(scene)}>
          <span class="picker-item-name">{scene.display_name || scene.name}</span>
          <span class="picker-item-source">{scene.source}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .scene-picker {
    position: relative;
    min-width: 0;
    width: 100%;
  }

  .picker-trigger {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.03);
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 12px;
    cursor: pointer;
    transition: all 0.18s;
    overflow: hidden;
  }

  .picker-trigger:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: var(--border-hover);
  }

  .picker-trigger.active {
    color: var(--text-primary);
    background: rgba(100, 180, 255, 0.1);
    border-color: rgba(100, 180, 255, 0.32);
  }

  .picker-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    text-align: left;
  }

  .picker-chevron {
    font-size: 10px;
    color: var(--text-muted);
    flex-shrink: 0;
  }

  .picker-menu {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 30;
    max-height: 260px;
    overflow-y: auto;
    background: rgba(18, 18, 28, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 10px;
    padding: 4px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    box-shadow: 0 10px 32px rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }

  .picker-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    padding: 7px 10px;
    background: transparent;
    border: 0;
    border-radius: 6px;
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.15s;
    text-align: left;
  }

  .picker-item:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  .picker-default {
    color: var(--text-muted);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    margin-bottom: 2px;
    border-radius: 6px 6px 0 0;
  }

  .picker-item-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .picker-item-source {
    font-size: 9px;
    color: var(--text-muted);
    text-transform: uppercase;
    flex-shrink: 0;
  }
</style>
