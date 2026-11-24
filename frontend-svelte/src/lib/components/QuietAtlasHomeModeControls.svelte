<script>
  import { connected } from '$lib/stores/connection.js'
  import { automation, automationSourceLabel } from '$lib/stores/automation.js'
  import { setManualMode } from '$lib/stores/init.js'

  // Use the existing owner-authenticated mode API. Never write Hue directly.
  const MODES = [
    { id: 'relax', label: 'Relax' },
    { id: 'working', label: 'Working' },
    { id: 'watching', label: 'Watching' },
    { id: 'gaming', label: 'Gaming' },
    { id: 'cooking', label: 'Cooking' },
    { id: 'social', label: 'Party' },
    { id: 'sleeping', label: 'Sleep' },
  ]
  const KNOWN_HOUSE_STATES = ['home', 'winding_down', 'away', 'sleeping']
  const MODE_NAMES = Object.fromEntries(MODES.map(({ id, label }) => [id, label]))

  let selectedMode = ''
  let pending = false
  let armedMode = null
  let feedback = ''

  $: canChange = $connected && KNOWN_HOUSE_STATES.includes($automation.house_state ?? '')
  $: reportedMode = $automation.house_state === 'sleeping'
    ? 'Sleeping'
    : $automation.house_state === 'away'
      ? 'Away'
      : MODE_NAMES[$automation.mode] ?? ($automation.mode === 'idle' ? 'General' : 'Not reported')
  $: reportedOwner = canChange ? automationSourceLabel($automation) : 'Mode status not verified'

  function changeSelection() {
    // Confirmation always belongs to the exact intended mode, never a stale selection.
    armedMode = null
    feedback = ''
  }

  async function requestMode(mode) {
    if (!canChange || pending || !mode) return

    // Explicit Auto while Sleeping can wake HomeHub; selecting a mode from Away
    // can relight the apartment. Require a second intentional press inline.
    const sensitiveAction = $automation.house_state === 'sleeping' || $automation.house_state === 'away'
    if (sensitiveAction && armedMode !== mode) {
      armedMode = mode
      feedback = 'HomeHub reports ' + reportedMode + '. This action may wake the home or change lights. Press the same action again to confirm.'
      return
    }

    armedMode = null
    pending = true
    feedback = 'Sending mode request to HomeHub…'
    try {
      const outcome = await setManualMode(mode)
      if (outcome === 'acknowledged') {
        feedback = mode === 'auto'
          ? 'Auto requested. Check the reported mode and lights.'
          : 'Mode requested. Check the reported mode and lights.'
      } else if (outcome === 'denied') {
        feedback = 'Couldn’t change the mode. Unlock owner controls and try again.'
      } else if (outcome === 'busy') {
        feedback = 'Another mode change is pending.'
      } else {
        feedback = 'Change unconfirmed. Check the current mode before trying again.'
      }
    } catch {
      feedback = 'Change unconfirmed. Check the current mode before trying again.'
    } finally {
      pending = false
    }
  }
</script>

<section class="mode-controls" aria-labelledby="home-modes-heading">
  <div class="mode-heading">
    <div class="mode-current">
      <h2 id="home-modes-heading">Modes</h2>
      <div class="reported-mode">
        <strong>{reportedMode}</strong>
        <span>{reportedOwner}</span>
      </div>
    </div>
    <button
      class="auto-action"
      type="button"
      disabled={!canChange || pending}
      aria-label="Return lights to automatic mode"
      on:click={() => requestMode('auto')}
    >Return to Auto</button>
  </div>

  <details class="mode-picker">
    <summary>Change mode</summary>
    <div class="mode-actions">
      <label class="mode-select" for="home-mode-choice">
        <span class="sr-only">Choose mode</span>
        <select id="home-mode-choice" bind:value={selectedMode} disabled={!canChange || pending} on:change={changeSelection}>
          <option value="" disabled>Select mode</option>
          {#each MODES as mode (mode.id)}
            <option value={mode.id}>{mode.label}</option>
          {/each}
        </select>
      </label>
      <button
        class="apply-action"
        type="button"
        disabled={!canChange || pending || !selectedMode}
        on:click={() => requestMode(selectedMode)}
      >{pending ? 'Applying…' : 'Apply mode'}</button>
    </div>
    <p class="mode-note">Adjusting a light pauses automatic changes to that light. Return to Auto requests that HomeHub clear manual holds and choose the mode again.</p>
  </details>

  {#if !canChange}
    <p class="mode-feedback" role="status">Mode changes unavailable until HomeHub reports a connected house state.</p>
  {:else if feedback}
    <p class="mode-feedback" role="status" aria-live="polite">{feedback}</p>
  {/if}
</section>

<style>
  .mode-controls {margin:16px 0 18px;padding:16px 18px 4px;border:1px solid var(--line);border-radius:19px;background:linear-gradient(130deg,var(--stage),var(--deep));color:var(--ink);min-width:0;}
  .mode-heading {display:flex;align-items:center;justify-content:space-between;gap:12px;}
  .mode-current {min-width:0;}
  h2 {margin:0 0 6px;font-size:13px;font-weight:600;color:var(--muted);letter-spacing:.015em;}
  .reported-mode {display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 10px;min-width:0;}
  .reported-mode strong {font-size:21px;font-weight:650;line-height:1.25;letter-spacing:-.035em;}
  .reported-mode span {font-size:12px;color:var(--muted);overflow-wrap:anywhere;}
  .mode-picker {margin-top:12px;border-top:1px solid var(--line);font-size:14px;}
  .mode-picker summary {min-height:44px;display:flex;align-items:center;justify-content:space-between;gap:12px;list-style:none;cursor:pointer;font-weight:600;color:var(--ink);}
  .mode-picker summary::-webkit-details-marker {display:none;}
  .mode-picker summary::after {content:'+';color:var(--gold);font-size:20px;font-weight:400;}
  .mode-picker[open] summary::after {content:'−';}
  .mode-note {color:var(--muted);font-size:12px;line-height:1.5;margin:10px 0 14px;max-width:70ch;}
  .mode-actions {display:grid;grid-template-columns:minmax(0,1fr) minmax(100px,auto);gap:9px;align-items:center;margin-top:6px;}
  button,select {font:inherit;min-height:48px;border-radius:13px;box-sizing:border-box;}
  button {padding:10px 14px;cursor:pointer;font-weight:650;}
  .auto-action {flex:0 0 auto;background:rgba(237,207,160,.10);color:var(--gold);border:1px solid rgba(237,207,160,.32);font-size:14px;}
  .apply-action {background:var(--gold);color:var(--deep);border:1px solid var(--gold);}
  .mode-select {min-width:0;}
  .mode-select select {width:100%;min-width:0;padding:0 10px;background:var(--deep);color:var(--ink);border:1px solid var(--line);}
  button:disabled,select:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible,select:focus-visible,summary:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  .mode-feedback {font-size:13px;line-height:1.5;margin:8px 0 12px;color:var(--ink);}
  .sr-only {position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
  @media(max-width:700px) {
    .mode-controls {margin:12px 0 14px;padding:14px 14px 3px;}
    .reported-mode {flex-direction:column;gap:3px;}
    .reported-mode strong {font-size:19px;}
    .auto-action {font-size:13px;padding:9px 11px;}
    .mode-picker {margin-top:10px;}
    .mode-select select,.apply-action {font-size:16px;}
  }
</style>
