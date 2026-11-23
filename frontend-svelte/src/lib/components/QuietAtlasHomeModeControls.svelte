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
    <div>
      <p class="eyebrow">LIGHTING MODES</p>
      <h2 id="home-modes-heading">Modes</h2>
    </div>
    <div class="reported-mode">
      <strong>{reportedMode}</strong>
      <span>{reportedOwner}</span>
    </div>
  </div>


  <div class="mode-actions">
    <button
      class="auto-action"
      type="button"
      disabled={!canChange || pending}
      aria-label="Return lights to automatic mode"
      on:click={() => requestMode('auto')}
    >Return to Auto</button>

    <label class="mode-select" for="home-mode-choice">
      <span>Choose mode</span>
      <select id="home-mode-choice" bind:value={selectedMode} disabled={!canChange || pending} on:change={changeSelection}>
        <option value="" disabled>Select an activity</option>
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

  <details class="mode-help">
    <summary>How modes work</summary>
    <p class="mode-note">Adjusting a light pauses automatic changes to that light. Return to Auto requests that HomeHub clear manual holds and choose the mode again.</p>
  </details>

  {#if !canChange}
    <p class="mode-feedback" role="status">Mode changes unavailable until HomeHub reports a connected house state.</p>
  {:else if feedback}
    <p class="mode-feedback" role="status" aria-live="polite">{feedback}</p>
  {/if}
</section>

<style>
  .mode-controls {margin:18px 0 21px;padding:19px 21px;border:1px solid var(--line);border-radius:17px;background:linear-gradient(120deg,var(--stage),var(--deep));color:var(--ink);min-width:0;}
  .mode-heading {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
  .eyebrow {margin:0 0 6px;color:var(--gold);font-size:11px;letter-spacing:.12em;font-weight:750;}
  h2 {margin:0;font-size:clamp(20px,2.5vw,26px);font-weight:600;letter-spacing:-.025em;}
  .reported-mode {display:flex;flex-direction:column;gap:4px;align-items:flex-end;text-align:right;min-width:0;}
  .reported-mode strong {font-size:15px;}
  .reported-mode span {font-size:12px;color:var(--muted);overflow-wrap:anywhere;}
  .mode-note {color:var(--muted);font-size:13px;line-height:1.55;margin:6px 0 0;max-width:70ch;}
  .mode-help {margin-top:12px;color:var(--muted);font-size:13px;}
  .mode-help summary {min-height:44px;display:flex;align-items:center;cursor:pointer;}
  .mode-actions {display:grid;grid-template-columns:minmax(130px,1fr) minmax(170px,1.35fr) minmax(120px,.85fr);gap:10px;align-items:end;}
  button,select {font:inherit;min-height:48px;border-radius:9px;box-sizing:border-box;}
  button {padding:10px 14px;cursor:pointer;font-weight:650;}
  .auto-action {background:var(--gold);color:var(--deep);border:1px solid var(--gold);}
  .apply-action {background:transparent;color:var(--ink);border:1px solid var(--line);}
  .mode-select {display:flex;flex-direction:column;gap:5px;min-width:0;font-size:12px;color:var(--muted);}
  .mode-select select {width:100%;min-width:0;padding:0 10px;background:var(--deep);color:var(--ink);border:1px solid var(--line);}
  button:disabled,select:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible,select:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  .mode-feedback {font-size:13px;line-height:1.5;margin:12px 0 0;color:var(--ink);}
  @media(max-width:700px) {
    .mode-controls {margin:12px 0 16px;padding:16px 14px;}
    .mode-heading {align-items:flex-start;}
    .reported-mode {align-items:flex-start;text-align:left;}
    .mode-actions {grid-template-columns:minmax(0,1fr) minmax(0,1fr);}
    .auto-action {grid-column:1/-1;}
    .mode-select {grid-column:1;min-width:0;}
    .apply-action {grid-column:2;}
  }
  @media(max-width:360px) {
    .mode-actions {grid-template-columns:minmax(0,1fr);}
    .auto-action,.mode-select,.apply-action {grid-column:1;}
  }
</style>
