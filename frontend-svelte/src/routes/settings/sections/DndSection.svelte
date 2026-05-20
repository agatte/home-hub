<script>
  import { onMount, onDestroy } from 'svelte'
  import { Moon } from 'lucide-svelte'
  import { automation } from '$lib/stores/automation.js'
  import { enableDND, clearDND } from '$lib/stores/init.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'

  const DURATIONS = [
    { label: '1 hour',       minutes: 60  },
    { label: '2 hours',      minutes: 120 },
    { label: '4 hours',      minutes: 240 },
    { label: 'All evening',  minutes: 360 },
  ]

  let selectedMinutes = 120
  /** @type {string | null} */
  let error = null
  /** @type {string | null} */
  let saving = null

  $: dndState = $automation?.dnd ?? { enabled: false, minutes_remaining: 0, expiry_utc: null }

  let tickNow = Date.now()
  /** @type {ReturnType<typeof setInterval> | null} */
  let tickTimer = null
  onMount(() => { tickTimer = setInterval(() => { tickNow = Date.now() }, 30_000) })
  onDestroy(() => { if (tickTimer) clearInterval(tickTimer) })

  $: remainingLabel = (() => {
    let m
    if (dndState.expiry_utc) {
      m = Math.max(0, Math.round((new Date(dndState.expiry_utc).getTime() - tickNow) / 60_000))
    } else {
      m = dndState.minutes_remaining ?? 0
    }
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`
  })()

  async function activate() {
    error = null
    saving = 'enable'
    try { await enableDND(selectedMinutes) }
    catch (e) { error = e instanceof Error ? e.message : 'Failed to enable DND' }
    finally { saving = null }
  }

  async function deactivate() {
    error = null
    saving = 'clear'
    try { await clearDND() }
    catch (e) { error = e instanceof Error ? e.message : 'Failed to clear DND' }
    finally { saving = null }
  }
</script>

<SettingsSection
  title="Do Not Disturb"
  description="Lock the current state. Autonomous mode changes, auto-play, TTS, and routines all pause until DND clears."
  icon={Moon}
>
  <div class="dnd-card" class:active={dndState.enabled}>
    <div class="dnd-status">
      <span class="status-dot" class:on={dndState.enabled}></span>
      <div class="status-meta">
        <span class="status-headline">{dndState.enabled ? `Active · ${remainingLabel} left` : 'Inactive'}</span>
        <span class="status-sub">
          {dndState.enabled
            ? 'The apartment will hold its current mode and lighting.'
            : 'The apartment is running autonomously.'}
        </span>
      </div>
    </div>

    {#if !dndState.enabled}
      <div class="duration-row" role="radiogroup" aria-label="DND duration">
        {#each DURATIONS as opt (opt.minutes)}
          <button
            type="button"
            class="duration-pill"
            class:selected={selectedMinutes === opt.minutes}
            role="radio"
            aria-checked={selectedMinutes === opt.minutes}
            on:click={() => (selectedMinutes = opt.minutes)}
          >
            {opt.label}
          </button>
        {/each}
      </div>
      <div class="action-row">
        <SettingButton variant="accent" loading={saving === 'enable'} on:click={activate}>
          {saving === 'enable' ? 'Locking…' : 'Enable Do Not Disturb'}
        </SettingButton>
      </div>
    {:else}
      <div class="action-row">
        <SettingButton variant="ghost" loading={saving === 'clear'} on:click={deactivate}>
          {saving === 'clear' ? 'Clearing…' : 'Clear Do Not Disturb'}
        </SettingButton>
      </div>
    {/if}

    {#if error}
      <p class="error">{error}</p>
    {/if}
  </div>
</SettingsSection>

<style>
  .dnd-card {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 18px;
    border-radius: var(--radius-sm, 10px);
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid var(--border);
    transition: background 0.2s, border-color 0.2s;
  }

  .dnd-card.active {
    background: rgba(140, 100, 200, 0.10);
    border-color: rgba(140, 100, 200, 0.4);
  }

  .dnd-status {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .status-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--text-muted);
    flex-shrink: 0;
    transition: background 0.2s, box-shadow 0.2s;
  }

  .status-dot.on {
    background: rgba(190, 165, 235, 1);
    box-shadow: 0 0 12px rgba(190, 165, 235, 0.7);
  }

  .status-meta {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .status-headline {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 22px;
    letter-spacing: 0.04em;
    color: var(--text-primary);
  }

  .status-sub {
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text-muted);
    line-height: 1.5;
  }

  .duration-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  .duration-pill {
    padding: 8px 14px;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .duration-pill:hover {
    border-color: var(--accent);
    color: var(--accent);
  }

  .duration-pill.selected {
    background: rgba(140, 100, 200, 0.22);
    border-color: rgba(140, 100, 200, 0.55);
    color: var(--text-primary);
  }

  .action-row {
    display: flex;
    gap: 10px;
  }

  .error {
    margin: 0;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--danger);
  }
</style>
