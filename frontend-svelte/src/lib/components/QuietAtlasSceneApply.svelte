<script>
  import { onDestroy } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { reviewSceneDraft } from '$lib/quietAtlas/controlDraft.js'

  export let scene = null
  export let connected = false
  export let pending = false
  export let onApplied = () => {}
  let feedback = ''
  let active = true
  onDestroy(() => { active = false })

  async function apply() {
    if (!connected || !scene || pending) return
    const intended = scene
    pending = true
    feedback = 'Checking scene…'
    try {
      // Re-read the inventory before every explicit apply. No URL query,
      // draft slider, mount, or browse operation can activate a scene.
      const result = await apiGet('/api/scenes')
      if (!active || !connected || scene !== intended) return
      const current = reviewSceneDraft(intended.id, result?.scenes, { connected, loading: false, error: '' })
      if (!current || JSON.stringify(current) !== JSON.stringify(intended)) {
        feedback = 'Scene changed or is unavailable. Refresh the library before applying.'
        return
      }
      const response = await apiPost(`/api/scenes/${encodeURIComponent(intended.id)}/activate`, {})
      if (!active) return
      feedback = response?.status === 'ok'
        ? 'Scene acknowledged. Check your lights for the actual result.'
        : 'Scene result unconfirmed. Check your lights before retrying.'
      if (response?.status === 'ok') onApplied()
    } catch {
      if (active) feedback = 'Scene could not be confirmed. Check your lights before trying again.'
    } finally {
      pending = false
    }
  }
</script>

<div class="scene-apply">
  <button type="button" disabled={!connected || !scene || pending} on:click={apply}>
    {pending ? 'Applying…' : 'Apply scene'}
  </button>
  {#if feedback}<p role="status" aria-live="polite">{feedback}</p>{/if}
</div>

<style>
  .scene-apply {display:grid;gap:9px;margin:12px 0;}
  button {min-height:48px;border:1px solid #e9ca94;border-radius:12px;background:#e9ca94;color:#15231b;font:inherit;font-weight:700;cursor:pointer;padding:10px 16px;}
  button:disabled {opacity:.5;cursor:not-allowed;}
  button:focus-visible {outline:3px solid #d7ebbf;outline-offset:3px;}
  p {font-size:13px;line-height:1.5;margin:0;}
</style>
