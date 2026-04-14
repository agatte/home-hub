<script>
  import { onMount } from 'svelte'
  import { get } from 'svelte/store'
  import { apiGet, apiPost, apiPut, apiDelete } from '$lib/api.js'
  import { lights } from '$lib/stores/lights.js'
  import { hueToHsl, ctToColor } from '$lib/utils/lightColor.js'
  import { SCENE_CATEGORIES } from '$lib/theme.js'
  import { Camera, Save, Trash2, X } from 'lucide-svelte'

  /** @type {number | null} numeric db id when editing, null when creating */
  export let editingId = null
  /** @type {() => void} */
  export let onSave = () => {}
  /** @type {() => void} */
  export let onCancel = () => {}

  let name = ''
  let category = 'custom'
  /** @type {string | null} */
  let effect = null
  /** @type {Record<string, {on: boolean, bri?: number, hue?: number, sat?: number, ct?: number}>} */
  let lightStates = {}
  /** @type {Array<{name: string, display_name: string}>} */
  let availableEffects = []
  let saving = false
  let error = ''

  const CATEGORY_OPTIONS = Object.entries(SCENE_CATEGORIES).map(([id, meta]) => ({
    id, label: meta.label,
  }))

  function captureCurrent() {
    const live = get(lights)
    /** @type {typeof lightStates} */
    const snapshot = {}
    for (const [id, l] of Object.entries(live)) {
      if (l.colormode === 'ct' && l.ct) {
        snapshot[id] = { on: l.on, bri: l.bri, ct: l.ct }
      } else {
        snapshot[id] = { on: l.on, bri: l.bri, hue: l.hue, sat: l.sat }
      }
    }
    lightStates = snapshot
  }

  function previewColor(state) {
    if (!state?.on) return 'var(--text-muted)'
    if (state.ct) return ctToColor(state.ct)
    if (state.hue != null && state.sat != null) {
      return hueToHsl(state.hue, state.sat, state.bri ?? 200)
    }
    return 'var(--text-muted)'
  }

  function lightName(id) {
    return get(lights)[id]?.name ?? `Light ${id}`
  }

  onMount(async () => {
    // Load available effects for dropdown
    try {
      const data = await apiGet('/api/scenes/effects')
      availableEffects = data.effects || []
    } catch {
      /* no v2 / effects unavailable */
    }

    if (editingId != null) {
      // Edit mode — fetch existing scene
      try {
        const resp = await apiGet('/api/scenes/custom')
        const scene = (resp.scenes || []).find((s) => s.id === editingId)
        if (scene) {
          name = scene.name
          category = scene.category || 'custom'
          effect = scene.effect || null
          lightStates = scene.light_states || {}
        }
      } catch {
        error = 'Failed to load scene'
      }
    } else {
      // New mode — seed from current live lights
      captureCurrent()
    }
  })

  async function preview() {
    // Apply each light state individually via PUT /api/lights/{id}
    for (const [id, state] of Object.entries(lightStates)) {
      try {
        await apiPut(`/api/lights/${id}`, { ...state, transitiontime: 4 })
      } catch {
        /* ignore individual failures */
      }
    }
  }

  async function save() {
    if (!name.trim()) {
      error = 'Name is required'
      return
    }
    if (Object.keys(lightStates).length === 0) {
      error = 'No light states captured — click Capture Current'
      return
    }

    saving = true
    error = ''
    const body = {
      name: name.trim(),
      light_states: lightStates,
      category,
      effect: effect || null,
    }

    try {
      if (editingId != null) {
        await apiPut(`/api/scenes/custom/${editingId}`, body)
      } else {
        await apiPost('/api/scenes/custom', body)
      }
      saving = false
      onSave()
    } catch (e) {
      saving = false
      error = e instanceof Error ? e.message : 'Save failed'
    }
  }

  async function remove() {
    if (editingId == null) return
    if (!confirm(`Delete scene "${name}"?`)) return
    try {
      await apiDelete(`/api/scenes/custom/${editingId}`)
      onSave()
    } catch (e) {
      error = e instanceof Error ? e.message : 'Delete failed'
    }
  }
</script>

<div class="scene-editor">
  <div class="editor-header">
    <span class="editor-title">{editingId != null ? 'Edit scene' : 'New scene'}</span>
    <button class="icon-btn" on:click={onCancel} aria-label="Cancel">
      <X size={14} strokeWidth={2} />
    </button>
  </div>

  <div class="editor-row">
    <input
      class="editor-input name-input"
      type="text"
      placeholder="Scene name"
      bind:value={name}
      maxlength="100"
    />
  </div>

  <div class="editor-row editor-row-split">
    <label class="field">
      <span class="field-label">Category</span>
      <select class="editor-select" bind:value={category}>
        {#each CATEGORY_OPTIONS as opt}
          <option value={opt.id}>{opt.label}</option>
        {/each}
      </select>
    </label>

    <label class="field">
      <span class="field-label">Effect</span>
      <select class="editor-select" bind:value={effect}>
        <option value={null}>None</option>
        {#each availableEffects as e}
          <option value={e.name}>{e.display_name}</option>
        {/each}
      </select>
    </label>
  </div>

  <div class="editor-capture">
    <button class="capture-btn" on:click={captureCurrent} title="Snapshot the current live light state">
      <Camera size={13} strokeWidth={1.8} />
      Capture current
    </button>
    <span class="capture-hint">{Object.keys(lightStates).length} lights captured</span>
  </div>

  <div class="preview-dots">
    {#each Object.entries(lightStates) as [id, state]}
      <div class="preview-row">
        <span
          class="preview-dot"
          class:off={!state.on}
          style="background: {previewColor(state)}"
        ></span>
        <span class="preview-name">{lightName(id)}</span>
        {#if state.on && state.bri != null}
          <span class="preview-meta">{Math.round((state.bri / 254) * 100)}%</span>
        {/if}
      </div>
    {/each}
    {#if Object.keys(lightStates).length === 0}
      <span class="preview-empty">No lights captured yet</span>
    {/if}
  </div>

  {#if error}
    <div class="editor-error">{error}</div>
  {/if}

  <div class="editor-actions">
    {#if editingId != null}
      <button class="action-btn danger-btn" on:click={remove} aria-label="Delete scene">
        <Trash2 size={13} strokeWidth={1.8} />
        Delete
      </button>
    {/if}
    <div class="action-spacer"></div>
    <button class="action-btn" on:click={preview}>Preview</button>
    <button class="action-btn primary-btn" on:click={save} disabled={saving}>
      <Save size={13} strokeWidth={1.8} />
      {saving ? 'Saving...' : 'Save'}
    </button>
  </div>
</div>

<style>
  .scene-editor {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    margin-bottom: 8px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    animation: editorIn 0.18s ease-out;
  }

  @keyframes editorIn {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .editor-title {
    font-family: var(--font-body);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--text-muted);
  }

  .icon-btn {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    border: none;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.15s, background 0.15s;
  }

  .icon-btn:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
  }

  .editor-row {
    display: flex;
    gap: 8px;
  }

  .editor-row-split {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .field-label {
    font-family: var(--font-body);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: var(--text-muted);
  }

  .editor-input,
  .editor-select {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.3);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    outline: none;
    transition: border-color 0.15s;
  }

  .editor-input:focus,
  .editor-select:focus {
    border-color: var(--accent);
  }

  .name-input {
    font-size: 13px;
    font-weight: 500;
  }

  .editor-capture {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .capture-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }

  .capture-btn:hover {
    color: var(--text-primary);
    border-color: var(--border-hover);
    background: rgba(255, 255, 255, 0.04);
  }

  .capture-hint {
    font-family: var(--font-body);
    font-size: 10px;
    color: var(--text-muted);
  }

  .preview-dots {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 6px 0;
  }

  .preview-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .preview-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
    border: 1px solid rgba(255, 255, 255, 0.15);
  }

  .preview-dot.off {
    opacity: 0.3;
  }

  .preview-name {
    flex: 1;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-secondary);
  }

  .preview-meta {
    font-family: var(--font-body);
    font-size: 10px;
    color: var(--text-muted);
  }

  .preview-empty {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    font-style: italic;
  }

  .editor-error {
    padding: 6px 10px;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.2);
    border-radius: 6px;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--danger);
  }

  .editor-actions {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .action-spacer {
    flex: 1;
  }

  .action-btn {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
  }

  .action-btn:hover:not(:disabled) {
    color: var(--text-primary);
    border-color: var(--border-hover);
    background: rgba(255, 255, 255, 0.04);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .primary-btn {
    border-color: var(--accent);
    color: var(--accent);
  }

  .primary-btn:hover:not(:disabled) {
    background: rgba(74, 108, 247, 0.1);
  }

  .danger-btn {
    border-color: rgba(239, 68, 68, 0.4);
    color: var(--danger);
  }

  .danger-btn:hover {
    background: rgba(239, 68, 68, 0.08);
  }
</style>
