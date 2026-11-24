<script>
  import { Power } from 'lucide-svelte'
  import { apiPost } from '$lib/api.js'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { automation } from '$lib/stores/automation.js'

  let armed = false
  /** @type {string | null} */
  let armedState = null
  let pending = false
  let feedback = ''
  $: available = $connected && $deviceStatus.hue === true && $deviceStatus.light_command_results === true &&
    ['home','winding_down','away','sleeping'].includes($automation.house_state ?? '')
  $: if (armed && (!available || armedState !== $automation.house_state)) cancel()
  function cancel() { armed = false; armedState = null }
  function arm() {
    if (!available || pending) return
    armed = true
    armedState = $automation.house_state
    feedback = ''
  }
  async function confirmOff() {
    if (!available || pending || !armed || armedState !== $automation.house_state) { cancel(); return }
    cancel()
    pending = true
    feedback = 'Requesting All Off…'
    try {
      // Existing guarded endpoint; server owns per-fixture authorization.
      const result = await apiPost('/api/lights/all', { on: false }, { timeout: 20000 })
      const valid = result && ['updated','blocked','unavailable','uncertain'].every(key => Array.isArray(result[key]))
      if (valid && result.status === 'ok' && result.updated.length > 0 && !result.blocked.length && !result.unavailable.length && !result.uncertain.length) {
        feedback = 'HomeHub acknowledged All Off. Verify the reported light states.'
      } else if (valid && result.status === 'partial_failure') {
        feedback = 'All Off partly applied or blocked: ' + result.blocked.length + ' protected, ' + result.unavailable.length + ' unavailable, ' + result.uncertain.length + ' uncertain. Check your lights before another action.'
      } else {
        feedback = 'All Off result unconfirmed. Check your lights before another action.'
      }
    } catch {
      feedback = 'All Off result unconfirmed. Check your lights before another action.'
    } finally { pending = false }
  }
</script>

<svelte:window on:blur={cancel} />
<svelte:document on:visibilitychange={cancel} />

<section class="off-card" aria-label="All lights off" aria-busy={pending}>
  <div class="off-row">
    <div><strong>All lights</strong><p>Separate from activity modes. Existing ownership protections apply.</p></div>
    <button class="off" type="button" disabled={!available || pending} on:click={arm}><Power size={19} strokeWidth={1.8} /> All Off</button>
  </div>
  {#if armed}
    <div class="confirmation" role="group" aria-label="Confirm All Off">
      <p>Request off for every configured light? Protected lights may remain on.</p>
      <div class="actions"><button type="button" on:click={cancel}>Cancel</button><button type="button" class="off" disabled={!available || pending} on:click={confirmOff}>Confirm All Off</button></div>
    </div>
  {/if}
  {#if !available}<p class="feedback" role="status">All Off unavailable until guarded lighting and house state are reported.</p>{/if}
  {#if feedback}<p class="feedback" role="status">{feedback}</p>{/if}
</section>

<style>
  .off-card {margin:0 0 18px;padding:14px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-card);background:var(--hh-card-background);color:var(--hh-ink);min-width:0;}
  .off-row {display:flex;align-items:center;justify-content:space-between;gap:12px;}
  .off-row>div {min-width:0;}
  strong {font-size:14px;}
  p {font-size:12px;line-height:1.5;margin:4px 0 0;color:var(--hh-muted);}
  button {display:inline-flex;align-items:center;justify-content:center;gap:7px;flex-shrink:0;min-height:44px;padding:8px 13px;border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);background:var(--hh-control);color:var(--hh-ink);font:inherit;font-size:13px;font-weight:650;cursor:pointer;}
  button.off {border-color:rgba(214,137,131,.55);color:var(--hh-ink);}
  button:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible {outline:3px solid var(--hh-focus);outline-offset:2px;}
  .confirmation {border-top:1px solid var(--hh-line);margin-top:12px;padding-top:10px;}
  .actions {display:flex;justify-content:flex-end;flex-wrap:wrap;gap:8px;margin-top:10px;}
  .feedback {margin-top:10px;}
</style>
