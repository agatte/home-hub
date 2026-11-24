<script>
  import { Gamepad2, Monitor, Tv, ChefHat, Flame, PartyPopper, Moon, Bot } from 'lucide-svelte'
  import { modeTone } from '$lib/quietAtlas/widgetTone.js'
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

  const MODE_ICONS = { relax: Flame, working: Monitor, watching: Tv, gaming: Gamepad2, cooking: ChefHat, social: PartyPopper, sleeping: Moon, auto: Bot }
  const CHOICES = [...MODES, { id: 'auto', label: 'Auto' }]

  let pending = false
  /** @type {string | null} */
  let armedMode = null
  /** @type {string | null} */
  let armedHouseState = null
  /** @type {string | null} */
  let pendingMode = null
  let feedback = ''

  $: canChange = $connected && KNOWN_HOUSE_STATES.includes($automation.house_state ?? '')
  $: reportedMode = !canChange ? 'Unverified' : $automation.house_state === 'sleeping'
    ? 'Sleeping'
    : $automation.house_state === 'away'
      ? 'Away'
      : MODE_NAMES[$automation.mode] ?? ($automation.mode === 'idle' ? 'General' : 'Not reported')
  $: reportedOwner = canChange ? automationSourceLabel($automation) : 'Mode status not verified'

  $: if (armedMode && (!canChange || armedHouseState !== $automation.house_state)) cancelConfirmation()
  $: activeId = canChange ? ($automation.override_user_owned
    ? ($automation.house_state === 'sleeping' ? 'sleeping' : $automation.mode)
    : 'auto') : null

  function cancelConfirmation() {
    armedMode = null
    armedHouseState = null
  }

  /** @param {string | null} mode @param {boolean} [confirmed] */
  async function requestMode(mode, confirmed = false) {
    if (!canChange || pending || !CHOICES.some(choice => choice.id === mode)) return
    if (confirmed && (armedMode !== mode || armedHouseState !== $automation.house_state)) {
      cancelConfirmation()
      return
    }

    // Sleep and actions from Away/Sleeping can change the apartment's
    // lifecycle or lighting. Use a separate confirmation, not a double tap.
    const sensitiveAction = mode === 'sleeping' || $automation.house_state === 'sleeping' || $automation.house_state === 'away'
    if (sensitiveAction && !confirmed) {
      armedMode = mode
      armedHouseState = $automation.house_state
      feedback = ''
      return
    }

    cancelConfirmation()
    pending = true
    pendingMode = mode
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
      pendingMode = null
    }
  }
</script>

<svelte:window on:blur={cancelConfirmation} />
<svelte:document on:visibilitychange={cancelConfirmation} />

<section class="mode-controls" aria-labelledby="home-modes-heading">
  <div class="mode-heading">
    <div class="mode-current">
      <h2 id="home-modes-heading">Modes</h2>
      <div class="reported-mode">
        <strong>{reportedMode}</strong>
        <span>{reportedOwner}</span>
      </div>
    </div>
    <span class="mode-caption">{canChange ? 'Choose a mode' : 'Unavailable'}</span>
  </div>

  <div class="mode-grid" role="group" aria-label="Choose an activity or Auto">
    {#each CHOICES as mode (mode.id)}
      <button
        class="mode-tile"
        class:active={activeId === mode.id}
        class:auto-tile={mode.id === 'auto'}
        class:armed={armedMode === mode.id}
        data-palette={modeTone(mode.label, true)}
        type="button"
        disabled={!canChange || pending}
        aria-pressed={activeId === mode.id}
        aria-label={mode.id === 'auto' ? 'Return to Auto' : mode.label}
        on:click={() => requestMode(mode.id)}
      >
        <span class="mode-icon"><svelte:component this={MODE_ICONS[mode.id]} size={22} strokeWidth={1.7} /></span>
        <span class="mode-label">{mode.label}</span>
        {#if pendingMode === mode.id}<span class="mode-indicator" aria-hidden="true">…</span>
        {:else if activeId === mode.id}<span class="mode-indicator" aria-hidden="true">●</span>{/if}
      </button>
    {/each}
  </div>

  {#if armedMode}
    <div class="confirmation" role="group" aria-label="Confirm mode change">
      <p><strong>{armedMode === 'sleeping' ? 'Enter Sleep?' : 'Change from ' + reportedMode + '?'}</strong> This may change house state or lighting.</p>
      <div class="confirmation-actions">
        <button type="button" class="cancel" on:click={cancelConfirmation}>Cancel</button>
        <button type="button" class="confirm" disabled={!canChange || pending} on:click={() => requestMode(armedMode, true)}>Confirm {armedMode === 'auto' ? 'Auto' : MODE_NAMES[armedMode]}</button>
      </div>
    </div>
  {/if}

  {#if !canChange}
    <p class="mode-feedback" role="status">Mode changes unavailable until HomeHub reports a connected house state.</p>
  {:else if feedback}
    <p class="mode-feedback" role="status" aria-live="polite">{feedback}</p>
  {/if}
  <p class="mode-note">Auto requests that HomeHub clear manual holds and choose the mode again.</p>
</section>

<style>
  .mode-controls {margin:16px 0 18px;padding:16px 18px 12px;border:1px solid var(--line);border-radius:var(--hh-radius-panel,20px);background:var(--hh-card-background,linear-gradient(130deg,var(--stage),var(--deep)));color:var(--ink);min-width:0;container-type:inline-size;}
  .mode-heading {display:flex;align-items:flex-end;justify-content:space-between;gap:8px 12px;margin-bottom:14px;flex-wrap:wrap;}
  .mode-current {min-width:0;}
  h2 {margin:0 0 5px;font-size:12px;font-weight:650;color:var(--muted);letter-spacing:.025em;}
  .reported-mode {display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;min-width:0;}
  .reported-mode strong {font-size:23px;font-weight:650;line-height:1.2;letter-spacing:-.035em;}
  .reported-mode span,.mode-caption {font-size:12px;color:var(--muted);overflow-wrap:anywhere;}
  .mode-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;}
  .mode-tile {position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;min-width:0;min-height:76px;padding:10px 3px;border:1px solid var(--line);border-radius:var(--hh-radius-card,14px);color:var(--ink);background:var(--hh-control);cursor:pointer;font:inherit;}
  .mode-icon {display:grid;place-items:center;width:32px;height:32px;border-radius:10px;background:var(--event-from,#344640);color:var(--event-accent,#b6c8bb);}
  .mode-label {font-size:12px;font-weight:650;line-height:1.2;overflow-wrap:anywhere;}
  .mode-tile:hover:not(:disabled) {background:var(--hh-control-hover);border-color:var(--gold);}
  .mode-tile.active {background:var(--hh-expressive,var(--hh-control));border-color:var(--event-accent,var(--gold));color:#faf8f5;}
  .mode-tile.auto-tile {border-color:var(--gold);}
  .mode-tile.auto-tile .mode-icon {background:var(--deep);color:var(--gold);}
  .mode-tile.auto-tile.active {background:var(--hh-control-hover);color:var(--ink);border:2px solid var(--gold);}
  .mode-tile.armed {outline:2px solid var(--gold);outline-offset:1px;}
  .mode-indicator {position:absolute;right:6px;top:4px;font-size:9px;color:currentColor;}
  .confirmation {display:grid;gap:10px;padding:12px;margin-top:12px;border:1px solid var(--gold);border-radius:var(--hh-radius-control);background:var(--deep);}
  .confirmation p {font-size:13px;line-height:1.5;margin:0;}
  .confirmation-actions {display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;}
  .confirmation-actions button {font:inherit;font-size:13px;font-weight:650;min-height:44px;padding:9px 14px;border-radius:var(--hh-radius-control);cursor:pointer;}
  .cancel {background:var(--hh-control);color:var(--ink);border:1px solid var(--line);}
  .confirm {background:var(--gold);color:var(--deep);border:1px solid var(--gold);}
  button:disabled {opacity:.55;cursor:not-allowed;}
  button:focus-visible {outline:3px solid var(--gold);outline-offset:3px;}
  .mode-note,.mode-feedback {font-size:12px;line-height:1.5;margin:10px 0 0;color:var(--muted);}
  .mode-feedback {color:var(--ink);}
  @container (min-width: 780px) {.mode-grid {grid-template-columns:repeat(8,minmax(0,1fr));}.mode-tile{min-height:80px;}}
  @container (max-width: 280px) {.mode-grid{grid-template-columns:repeat(2,minmax(0,1fr));}.mode-tile{min-height:60px;flex-direction:row;gap:6px;}}
  @media(max-width:700px) {.mode-controls{margin:12px 0 14px;padding:12px;}.mode-heading{margin-bottom:12px;}.reported-mode strong{font-size:20px;}.mode-grid{gap:6px;}.mode-tile{min-height:72px;}.mode-label{font-size:12px;}}
</style>
