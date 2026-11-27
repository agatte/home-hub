<script>
  import { onMount } from 'svelte'
  import { Activity } from 'lucide-svelte'
  import { connected } from '$lib/stores/connection.js'
  import { apiPost } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import SettingRow from '$lib/components/settings/SettingRow.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'

  /** @type {any} */
  let health = null
  let healthPhase = 'checking'
  /** @type {string | null} */
  let saving = null
  /** @type {string | null} */
  let actionFeedback = null

  // HTTP health and this browser's authenticated live socket are separate
  // evidence. Never turn missing or stale socket frames into device outages.
  onMount(() => {
    /** @type {AbortController | null} */
    let active = null
    /** @type {ReturnType<typeof setTimeout> | null} */
    let activeTimeout = null
    let disposed = false

    function invalidate() {
      const previous = active
      active = null
      if (activeTimeout !== null) clearTimeout(activeTimeout)
      activeTimeout = null
      previous?.abort()
      health = null
      healthPhase = 'checking'
    }

    async function refresh() {
      if (disposed || active || document.visibilityState === 'hidden') return
      const request = new AbortController()
      active = request
      const timer = setTimeout(() => {
        if (active !== request) return
        active = null
        activeTimeout = null
        health = null
        healthPhase = 'unavailable'
        request.abort()
      }, 8000)
      activeTimeout = timer
      try {
        // Use a quiet, bounded same-origin diagnostic read. Expected
        // unavailability is rendered here, not as a recurring global toast.
        const response = await fetch('/health', {
          credentials: 'same-origin', cache: 'no-store', signal: request.signal,
        })
        if (!response.ok) throw new Error('Health unavailable')
        const snapshot = await response.json()
        if (!['healthy', 'degraded'].includes(snapshot?.status)) throw new Error('Invalid health snapshot')
        if (!disposed && active === request) {
          health = snapshot
          healthPhase = 'ready'
        }
      } catch {
        if (!disposed && active === request) {
          health = null
          healthPhase = 'unavailable'
        }
      } finally {
        clearTimeout(timer)
        if (active === request) {
          active = null
          activeTimeout = null
        }
      }
    }

    function onVisibilityChange() {
      // Do not display a previously observed device state after tab sleep.
      invalidate()
      if (document.visibilityState !== 'hidden') void refresh()
    }

    const interval = setInterval(refresh, 30000)
    document.addEventListener('visibilitychange', onVisibilityChange)
    void refresh()
    return () => {
      disposed = true
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      invalidate()
    }
  })

  /** @param {unknown} value */
  function deviceLabel(value) {
    return value === true ? 'Connected' : value === false ? 'Offline' : 'Unknown'
  }

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
  description="Your connections at a glance, with diagnostic tools available when you need them."
  icon={Activity}
>
  <SettingGroup title="Connections">
    <SettingRow label="Server" hint="Backend health (HTTP)">
      <span class="status-pill" class:ok={health?.status === 'healthy'} class:warn={health?.status === 'degraded'}>
        {healthPhase === 'checking' ? 'Checking' : healthPhase === 'unavailable' ? 'Unverified' : health?.status === 'degraded' ? 'Degraded' : 'Reachable'}
      </span>
    </SettingRow>
    <SettingRow label="Live updates" hint={$connected ? 'WebSocket connected' : 'No WebSocket ? page may be stale'}>
      <span class="status-pill" class:ok={$connected}>{$connected ? 'Connected' : 'Disconnected'}</span>
    </SettingRow>
    <SettingRow label="Hue Bridge" hint="Lighting + scenes">
      <span class="status-pill" class:ok={health?.devices?.hue_bridge === true} class:offline={health?.devices?.hue_bridge === false}>{deviceLabel(health?.devices?.hue_bridge)}</span>
    </SettingRow>
    <SettingRow label="Sonos Era 100" hint="Living room speaker">
      <span class="status-pill" class:ok={health?.devices?.sonos === true} class:offline={health?.devices?.sonos === false}>{deviceLabel(health?.devices?.sonos)}</span>
    </SettingRow>
    <SettingRow label="Pi-hole" hint="DNS + blocklists">
      <span class="status-pill" class:ok={health?.devices?.pihole === true} class:offline={health?.devices?.pihole === false}>{deviceLabel(health?.devices?.pihole)}</span>
    </SettingRow>
    {#if health}
      <SettingRow label="WebSocket clients" hint="Active dashboard sessions">
        <span class="value-pill">{Number.isInteger(health.websocket_clients) ? health.websocket_clients : 'Unknown'}</span>
      </SettingRow>
      {#if health.build_id}
        <SettingRow label="Build" hint="Active backend commit on this host">
          <span class="value-pill mono">{health.build_id}</span>
        </SettingRow>
      {/if}
    {/if}
  </SettingGroup>

  <details class="diagnostics">
    <summary><span><strong>Diagnostics</strong><small>Test notifications and speaker announcements</small></span><span class="disclosure" aria-hidden="true">⌄</span></summary>
    <p class="diagnostic-note">These tests send real notifications or play audio when you press a test button.</p>
    <SettingGroup>
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
      <p class="feedback" role="status">{actionFeedback}</p>
    {/if}
    </SettingGroup>
  </details>
</SettingsSection>

<style>
  .diagnostics{margin-top:12px;border-top:1px solid var(--border);padding-top:10px;}
  .diagnostics summary{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:52px;padding:8px 4px;cursor:pointer;list-style:none;color:var(--text-primary);}
  .diagnostics summary::-webkit-details-marker{display:none;}
  .diagnostics summary span:first-child{display:grid;gap:5px;}
  .diagnostics summary strong{font-size:15px;font-weight:600;}
  .diagnostics summary small{font-size:13px;color:var(--text-muted);line-height:1.4;}
  .diagnostics summary:focus-visible{outline:3px solid var(--hh-focus,#d5e7bd);outline-offset:2px;border-radius:8px;}
  .disclosure{color:var(--accent);font-size:21px;}
  .diagnostics[open] .disclosure{transform:rotate(180deg);}
  .diagnostics[open] summary{margin-bottom:10px;}
  .diagnostic-note{margin:0 4px 10px;font-size:13px;line-height:1.5;color:var(--text-muted);}

  .status-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--border);
    color: var(--text-muted);
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }

  .status-pill.offline {
    background: rgba(248, 113, 113, 0.12);
    border-color: rgba(248, 113, 113, 0.32);
    color: var(--danger);
  }

  .status-pill.warn {
    background: rgba(245, 158, 11, 0.12);
    border-color: rgba(245, 158, 11, 0.32);
    color: var(--warning, #fbbf24);
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

  @media (max-width: 600px) {
    .status-pill { box-sizing: border-box; min-height: 32px; padding: 6px 12px; font-size: 13px; line-height: 1.4; }
    .value-pill { box-sizing: border-box; min-width: 0; max-width: 100%; padding: 8px 11px; font-size: 13px; line-height: 1.4; overflow-wrap: anywhere; }
    .value-pill.mono { font-size: 12px; overflow-wrap: anywhere; word-break: break-all; }
    .feedback { margin: 10px 0 0; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
  }
</style>
