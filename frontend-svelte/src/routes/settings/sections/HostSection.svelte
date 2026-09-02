<script>
  import { onMount } from 'svelte'
  import { Laptop, TriangleAlert } from 'lucide-svelte'
  import { apiGet, apiPost } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'

  /** @type {any} */
  let status = null
  let loading = true
  let arming = false
  /** @type {string | null} */
  let error = null
  /** @type {string | null} */
  let armedMessage = null

  onMount(async () => {
    try {
      status = await apiGet('/api/host/status')
    } catch (e) {
      error = e instanceof Error ? e.message : 'Could not read host status'
    } finally {
      loading = false
    }
  })

  async function enterTravel() {
    const confirmed = window.confirm(
      'Take the Latitude out of the apartment?\n\n' +
      'HomeHub, the Latitude streaming detector, tunnel proxy, and kiosk will stop and stay off across reboot/login. ' +
      'Use “HomeHub Return Home” from Ubuntu when the Latitude is back.\n\n' +
      'Apartment DNS may still depend on this Latitude while #145 is open.'
    )
    if (!confirmed) return

    arming = true
    error = null
    try {
      const result = await apiPost('/api/host/travel', null, { timeout: 7000 })
      armedMessage = result?.message ?? 'Travel Mode armed — HomeHub is shutting down.'
      status = { ...(status ?? {}), mode: 'TRAVEL' }
    } catch (e) {
      error = e instanceof Error ? e.message : 'Could not arm Travel Mode'
      arming = false
    }
  }
</script>

<SettingsSection
  title="Host / Travel"
  description="Controls whether this Latitude is physically installed in the apartment or intentionally away."
  icon={Laptop}
>
  <div class="host-card">
    <div class="host-status">
      <span class="status-dot" class:travel={status?.mode === 'TRAVEL'}></span>
      <div class="status-meta">
        <span class="status-headline">
          {loading ? 'Checking host…' : `Host mode: ${status?.mode ?? 'UNKNOWN'}`}
        </span>
        <span class="status-sub">
          {status?.mode === 'TRAVEL'
            ? 'Apartment-specific Latitude services are intentionally suppressed.'
            : 'HomeHub is running as the apartment host.'}
        </span>
      </div>
    </div>

    <div class="warning-row">
      <TriangleAlert size={17} strokeWidth={1.7} />
      <span>{status?.dns_warning ?? 'Apartment DNS failover is tracked separately in #145.'}</span>
    </div>

    {#if armedMessage}
      <div class="armed-message">{armedMessage}</div>
    {:else if status?.mode !== 'TRAVEL'}
      <div class="action-row">
        <SettingButton variant="danger" loading={arming} disabled={status?.can_control === false} on:click={enterTravel}>
          {arming ? 'Arming Travel…' : 'Enter Travel Mode'}
        </SettingButton>
      </div>
      <p class="hint">
        {#if status?.can_control === false}
          Travel can only be armed from the Latitude kiosk itself.
        {:else}
          The button acknowledges first, then stops HomeHub and the kiosk. Return with the Ubuntu app
          <strong>HomeHub Return Home</strong> after reconnecting to the apartment Wi-Fi.
        {/if}
      </p>
    {/if}

    {#if error}<p class="error">{error}</p>{/if}
  </div>
</SettingsSection>

<style>
  .host-card {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 18px;
    border-radius: var(--radius-sm, 10px);
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid var(--border);
  }
  .host-status { display: flex; align-items: center; gap: 14px; }
  .status-dot {
    width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
    background: #4ade80; box-shadow: 0 0 10px rgba(74, 222, 128, 0.45);
  }
  .status-dot.travel {
    background: #f59e0b; box-shadow: 0 0 10px rgba(245, 158, 11, 0.45);
  }
  .status-meta { display: flex; flex-direction: column; gap: 3px; }
  .status-headline { color: var(--text-primary); font-size: 14px; font-weight: 600; }
  .status-sub, .hint { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
  .warning-row {
    display: flex; gap: 10px; align-items: flex-start; padding: 11px 12px;
    border: 1px solid rgba(245, 158, 11, 0.28); border-radius: 9px;
    background: rgba(245, 158, 11, 0.07); color: #f6c56c; font-size: 12px; line-height: 1.45;
  }
  .warning-row :global(svg) { flex-shrink: 0; margin-top: 1px; }
  .action-row { display: flex; }
  .hint { margin: -4px 0 0; }
  .armed-message { color: #86efac; font-size: 13px; font-weight: 600; }
  .error { margin: 0; color: var(--danger); font-size: 12px; }
</style>
