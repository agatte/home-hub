<script>
  import { onMount } from 'svelte'
  import { Activity, Wifi, Speaker, Shield, Plug } from 'lucide-svelte'
  import { connected, deviceStatus } from '$lib/stores/connection.js'
  import { apiGet, apiPost } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import SettingRow from '$lib/components/settings/SettingRow.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'

  /** @type {any} */
  let health = null
  /** @type {string | null} */
  let saving = null
  /** @type {string | null} */
  let actionFeedback = null

  onMount(async () => {
    try { health = await apiGet('/health') } catch {}
  })

  async function testTTS() {
    saving = 'tts'
    actionFeedback = null
    try {
      await apiPost('/api/sonos/tts', {
        text: 'Home Hub is connected and working.',
        volume: 10,
      })
      actionFeedback = 'TTS sent to Sonos'
    } catch (e) {
      actionFeedback = e instanceof Error ? `TTS failed: ${e.message}` : 'TTS failed'
    } finally {
      saving = null
    }
  }

  async function fireNotification() {
    saving = 'notif'
    actionFeedback = null
    try {
      await apiPost('/api/notification/test', { kind: 'suggestion' })
      actionFeedback = 'Notification dispatched (desktop + ntfy)'
    } catch (e) {
      actionFeedback = e instanceof Error ? `Notification failed: ${e.message}` : 'Notification failed'
    } finally {
      saving = null
    }
  }
</script>

<SettingsSection
  title="Overview"
  description="At-a-glance device health and quick diagnostics. Everything else lives in the rail to the left."
  icon={Activity}
>
  <SettingGroup title="Connections">
    <SettingRow label="Server" hint={$connected ? 'WebSocket connected' : 'No WebSocket — page may be stale'}>
      <span class="status-pill" class:ok={$connected}>{$connected ? 'Online' : 'Offline'}</span>
    </SettingRow>
    <SettingRow label="Hue Bridge" hint="Lighting + scenes">
      <span class="status-pill" class:ok={$deviceStatus.hue}>{$deviceStatus.hue ? 'Connected' : 'Offline'}</span>
    </SettingRow>
    <SettingRow label="Sonos Era 100" hint="Living room speaker">
      <span class="status-pill" class:ok={$deviceStatus.sonos}>{$deviceStatus.sonos ? 'Connected' : 'Offline'}</span>
    </SettingRow>
    {#if health}
      <SettingRow label="Pi-hole" hint="DNS + blocklists">
        <span class="status-pill" class:ok={health.devices?.pihole}>
          {health.devices?.pihole ? 'Connected' : 'Offline'}
        </span>
      </SettingRow>
      <SettingRow label="WebSocket clients" hint="Active dashboard sessions">
        <span class="value-pill">{health.websocket_clients ?? 0}</span>
      </SettingRow>
      {#if health.build_id}
        <SettingRow label="Build" hint="Active backend commit on this host">
          <span class="value-pill mono">{health.build_id}</span>
        </SettingRow>
      {/if}
    {/if}
  </SettingGroup>

  <SettingGroup title="Diagnostics" hint="Smoke-test the notification + audio chain.">
    <SettingRow label="Test TTS" hint="Plays 'Home Hub is connected and working.' on Sonos at volume 10">
      <SettingButton variant="ghost" loading={saving === 'tts'} on:click={testTTS}>
        {saving === 'tts' ? 'Speaking…' : 'Test TTS'}
      </SettingButton>
    </SettingRow>
    <SettingRow label="Test notification" hint="Fires a synthetic 'suggestion' through WS + ntfy.sh push">
      <SettingButton variant="ghost" loading={saving === 'notif'} on:click={fireNotification}>
        {saving === 'notif' ? 'Firing…' : 'Fire notification'}
      </SettingButton>
    </SettingRow>
    {#if actionFeedback}
      <p class="feedback">{actionFeedback}</p>
    {/if}
  </SettingGroup>
</SettingsSection>

<style>
  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(248, 113, 113, 0.12);
    border: 1px solid rgba(248, 113, 113, 0.32);
    color: var(--danger);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }

  .status-pill.ok {
    background: rgba(52, 211, 153, 0.14);
    border-color: rgba(52, 211, 153, 0.32);
    color: var(--success);
  }

  .value-pill {
    display: inline-flex;
    padding: 4px 10px;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 12px;
    font-weight: 600;
  }

  .value-pill.mono {
    font-family: ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace;
    font-size: 11px;
  }

  .feedback {
    margin: 8px 4px 0;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.5;
  }
</style>
