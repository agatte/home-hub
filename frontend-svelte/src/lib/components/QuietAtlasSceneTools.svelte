<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import { reviewSceneDraft } from '$lib/quietAtlas/controlDraft.js'

  /** @type {ReturnType<typeof reviewSceneDraft>} */
  export let scene = null
  export let connected = false
  export let blocked = false
  export let pending = false
  export let onChanged = () => {}

  /** @type {Array<{name:string,display_name:string,description?:string}>} */
  let effects = []
  let effectsReady = false
  let effectsLoading = false
  let effectError = ''
  let feedback = ''
  let active = false
  let generation = 0
  let trialUntil = 0
  let now = 0
  let trialName = ''
  $: remaining = Math.max(0, Math.ceil((trialUntil - now) / 1000))
  $: if (active && connected) void loadEffects()
  $: if (!connected) { generation += 1; effectsReady = false; effects = []; effectsLoading = false }

  async function loadEffects() {
    if (!active || !connected) return
    const ticket = ++generation
    effectsLoading = true
    effectsReady = false
    effectError = ''
    effects = []
    try {
      const result = await apiGet('/api/scenes/effects')
      if (!active || !connected || generation !== ticket) return
      if (result?.available !== true || !Array.isArray(result.effects)) {
        effectError = 'Hue effects are unavailable.'
        return
      }
      effects = result.effects.filter(e => typeof e?.name === 'string' && /^[a-z][a-z0-9_-]*$/.test(e.name) && e.name !== 'stop' && typeof e.display_name === 'string')
      effectsReady = true
    } catch {
      if (active && generation === ticket) effectError = 'Could not load Hue effects.'
    } finally {
      if (active && generation === ticket) effectsLoading = false
    }
  }

  onMount(() => {
    active = true
    now = Date.now()
    const timer = window.setInterval(() => { now = Date.now() }, 250)
    return () => window.clearInterval(timer)
  })
  onDestroy(() => { active = false; generation += 1 })

  function canSend() {
    return active && connected && !blocked && !pending && document.visibilityState === 'visible'
  }

  async function startTrial() {
    if (!canSend() || !scene || remaining > 0) return
    const intended = scene
    pending = true
    feedback = 'Checking scene…'
    try {
      const result = await apiGet('/api/scenes')
      if (!active || !connected || blocked || document.visibilityState !== 'visible' || scene !== intended) {
        feedback = 'Scene preview not started.'
        return
      }
      const current = reviewSceneDraft(intended.id, result?.scenes, { connected, loading: false, error: '' })
      if (!current || JSON.stringify(current) !== JSON.stringify(intended)) {
        feedback = 'Scene changed. Refresh the library before trying it.'
        return
      }
      const resultTry = await apiPost(`/api/scenes/${encodeURIComponent(intended.id)}/try`, {})
      if (!active) return
      if (resultTry?.status !== 'ok' || resultTry.revert_after !== 30 || typeof resultTry.snapshot_id !== 'string') {
        feedback = 'Couldn’t confirm the preview. Check your lights before trying again.'
        return
      }
      now = Date.now()
      trialUntil = now + 30000
      trialName = intended.name
      feedback = 'HomeHub will try to restore your previous lighting after 30 seconds.'
      onChanged()
    } catch {
      if (active) feedback = 'Couldn’t confirm the preview. Check your lights or end the preview if needed.'
    } finally { pending = false }
  }

  async function endTrial() {
    if (!canSend()) return
    pending = true
    feedback = 'Ending preview…'
    try {
      const result = await apiPost('/api/scenes/try/cancel', {})
      if (!active) return
      if (result?.status === 'reverted' || result?.status === 'discarded' || (result?.status === 'ok' && result.detail === 'No active trial')) {
        trialUntil = 0
        feedback = result.status === 'reverted' ? '' : result.status === 'discarded' ? 'Preview ended. Newer lighting changes were kept.' : 'No active trial.'
        onChanged()
      } else feedback = 'Couldn’t confirm the preview ended. Check your lights.'
    } catch {
      if (active) feedback = 'Couldn’t confirm the preview ended. Check your lights.'
    } finally { pending = false }
  }

  /** @param {string} effect */
  async function changeEffect(effect) {
    if (!canSend() || !effectsReady || remaining > 0 || (effect !== 'stop' && !effects.some(e => e.name === effect))) return
    pending = true
    feedback = 'Changing effect…'
    try {
      const result = await apiPost(`/api/scenes/effects/${encodeURIComponent(effect)}`, {})
      if (!active) return
      const accepted = result?.status === 'ok' && result.effect === (effect === 'stop' ? 'stopped' : effect)
      feedback = accepted ? '' : 'Effect result incomplete or unconfirmed. Check your lights.'
      if (accepted) onChanged()
    } catch {
      if (active) feedback = 'Couldn’t confirm the effect. Check your lights before trying again.'
    } finally { pending = false }
  }
</script>

<div class="tools">
  <div class="trial">
    <div class="heading"><strong>Try a scene</strong><span>30-second preview</span></div>
    {#if remaining > 0}<p>{trialName} · about {remaining}s remaining</p>
    {:else if trialUntil}<p>Preview time is up. Check that your previous lighting returned.</p>{/if}
    <div class="actions">
      <button type="button" disabled={!connected || blocked || pending || !scene || remaining > 0} on:click={startTrial}>Try for 30 seconds</button>
      <button type="button" disabled={!connected || blocked || pending} on:click={endTrial}>End preview</button>
    </div>
    <p>Ending the preview tries to restore your previous lighting without undoing newer changes. The timer continues even if you leave.</p>
  </div>
  <div class="effects">
    <div class="heading"><strong>Hue effects</strong><span>All lights</span></div>
    {#if effectsLoading}<p>Loading effects…</p>{/if}
    {#if effectError}<p role="status">{effectError}</p><button type="button" disabled={!connected || pending || blocked} on:click={loadEffects}>Retry effects</button>{/if}
    {#if effectsReady}
      <div class="actions">
        {#each effects as effect (effect.name)}
          <button type="button" title={effect.description ?? ''} disabled={!connected || blocked || pending || remaining > 0} on:click={() => changeEffect(effect.name)}>{effect.display_name}</button>
        {/each}
        <button type="button" disabled={!connected || blocked || pending || remaining > 0} on:click={() => changeEffect('stop')}>Stop effects</button>
      </div>
    {/if}
  </div>
  {#if feedback}<p class="feedback" role="status">{feedback}</p>{/if}
</div>

<style>
  .tools{display:grid;gap:12px;margin-top:14px;min-width:0;}
  .trial,.effects{border:1px solid #536956;border-radius:14px;background:#213127;padding:14px;min-width:0;}
  .heading{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:7px;}
  .heading strong{font-size:15px}.heading span,p{font-size:12px;line-height:1.5;color:#b9cabd;}
  .actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;}
  button{min-height:44px;max-width:100%;border:1px solid #7b967c;border-radius:10px;background:#2a4534;color:#ecf1e5;padding:9px 12px;font:inherit;font-size:13px;cursor:pointer;overflow-wrap:anywhere;}
  button:disabled{opacity:.5;cursor:not-allowed;}button:focus-visible{outline:3px solid #d1e9be;outline-offset:3px;}
  .feedback{border:1px solid #8a7754;border-radius:10px;padding:12px;color:#f1e3c4;}
</style>
