<script>
  import { onMount } from 'svelte'
  import { Network } from 'lucide-svelte'
  import { apiGet, apiPost, apiDelete } from '$lib/api.js'
  import SettingsSection from '$lib/components/settings/SettingsSection.svelte'
  import SettingGroup from '$lib/components/settings/SettingGroup.svelte'
  import SettingButton from '$lib/components/settings/SettingButton.svelte'
  import DnsHostRow from '$lib/components/settings/DnsHostRow.svelte'
  import BlocklistRow from '$lib/components/settings/BlocklistRow.svelte'

  const RECOMMENDED_LISTS = [
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/multi.txt', label: 'Hagezi Multi' },
    { url: 'https://big.oisd.nl/', label: 'OISD Full' },
    { url: 'https://v.firebog.net/hosts/AdguardDNS.txt', label: 'AdGuard DNS' },
    { url: 'https://v.firebog.net/hosts/Easyprivacy.txt', label: 'EasyPrivacy' },
    { url: 'https://v.firebog.net/hosts/Easylist.txt', label: 'EasyList' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/tif.txt', label: 'Hagezi TIF (Threats)' },
    { url: 'https://phishing.army/download/phishing_army_blocklist.txt', label: 'Phishing Army' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/fake.txt', label: 'Hagezi Fake/Scam' },
    { url: 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/native.winoffice.txt', label: 'Windows Telemetry' },
  ]

  // .lan, not .local — macOS/iOS treat .local as mDNS/Bonjour and may bypass
  // Pi-hole for those names. Keep in sync with Pi-hole's dns.hosts records.
  const DEFAULT_DNS_HOSTS = [
    { ip: '192.168.1.210', hostname: 'homehub.lan' },
    { ip: '192.168.1.210', hostname: 'pihole.lan' },
    { ip: '192.168.1.50',  hostname: 'hue.lan' },
    { ip: '192.168.1.157', hostname: 'sonos.lan' },
    { ip: '192.168.1.30',  hostname: 'desktop.lan' },
    { ip: '192.168.1.209', hostname: 'tablet.lan' },
  ]

  /** @type {any[] | null} */
  let dnsHosts = null
  /** @type {any[] | null} */
  let blocklists = null
  /** @type {any[] | null} */
  let allowDomains = null
  let piholeAvailable = false
  let newDnsHostname = ''
  let newDnsIp = ''
  let newBlocklistUrl = ''
  let newAllowDomain = ''
  /** @type {string | null} */
  let saving = null

  onMount(async () => {
    try {
      const resp = /** @type {any} */ (await apiGet('/api/pihole/dns'))
      dnsHosts = resp.dns_hosts || []
      piholeAvailable = true
    } catch { dnsHosts = null }
    try {
      const resp = /** @type {any} */ (await apiGet('/api/pihole/lists'))
      blocklists = resp.lists || []
    } catch { blocklists = null }
    try {
      const resp = /** @type {any} */ (await apiGet('/api/pihole/allow'))
      allowDomains = resp.allow || []
    } catch { allowDomains = null }
  })

  async function addDnsHost() {
    if (!newDnsHostname || !newDnsIp) return
    saving = 'dns-add'
    try {
      await apiPost('/api/pihole/dns', { ip: newDnsIp, hostname: newDnsHostname })
      newDnsHostname = ''
      newDnsIp = ''
      const resp = /** @type {any} */ (await apiGet('/api/pihole/dns'))
      dnsHosts = resp.dns_hosts || []
    } catch {}
    saving = null
  }

  /** @param {{ip: string, hostname: string}} record */
  async function deleteDnsHost(record) {
    saving = 'dns-del'
    try {
      await apiDelete(`/api/pihole/dns/${record.ip}/${record.hostname}`)
      dnsHosts = (dnsHosts || []).filter(
        (/** @type {any} */ r) => !(r.ip === record.ip && r.hostname === record.hostname)
      )
    } catch {}
    saving = null
  }

  async function addAllDefaultDns() {
    saving = 'dns-defaults'
    for (const host of DEFAULT_DNS_HOSTS) {
      const exists = (dnsHosts || []).some(
        (/** @type {any} */ r) => r.ip === host.ip && r.hostname === host.hostname
      )
      if (!exists) {
        try { await apiPost('/api/pihole/dns', host) } catch {}
      }
    }
    try {
      const resp = /** @type {any} */ (await apiGet('/api/pihole/dns'))
      dnsHosts = resp.dns_hosts || []
    } catch {}
    saving = null
  }

  /** @param {string} url */
  async function addBlocklist(url) {
    saving = 'list-add'
    try {
      await apiPost('/api/pihole/lists', { address: url })
      const resp = /** @type {any} */ (await apiGet('/api/pihole/lists'))
      blocklists = resp.lists || []
      newBlocklistUrl = ''
    } catch {}
    saving = null
  }

  /** @param {string} address */
  async function deleteBlocklist(address) {
    saving = 'list-del'
    try {
      await apiDelete(`/api/pihole/lists/${encodeURIComponent(address)}`)
      blocklists = (blocklists || []).filter((/** @type {any} */ l) => l.address !== address)
    } catch {}
    saving = null
  }

  async function addAllRecommendedLists() {
    saving = 'lists-recommended'
    const existing = new Set((blocklists || []).map((/** @type {any} */ l) => l.address))
    for (const list of RECOMMENDED_LISTS) {
      if (!existing.has(list.url)) {
        try { await apiPost('/api/pihole/lists', { address: list.url }) } catch {}
      }
    }
    try {
      const resp = /** @type {any} */ (await apiGet('/api/pihole/lists'))
      blocklists = resp.lists || []
    } catch {}
    saving = null
  }

  async function addAllowDomain() {
    const domain = newAllowDomain.trim().toLowerCase()
    if (!domain) return
    saving = 'allow-add'
    try {
      await apiPost('/api/pihole/allow', { domain, comment: 'added from dashboard' })
      newAllowDomain = ''
      const resp = /** @type {any} */ (await apiGet('/api/pihole/allow'))
      allowDomains = resp.allow || []
    } catch {}
    saving = null
  }

  /** @param {string} domain */
  async function deleteAllowDomain(domain) {
    saving = 'allow-del'
    try {
      await apiDelete(`/api/pihole/allow/${encodeURIComponent(domain)}`)
      allowDomains = (allowDomains || []).filter((/** @type {any} */ d) => d.domain !== domain)
    } catch {}
    saving = null
  }

  /** @param {string} url */
  function getListLabel(url) {
    const rec = RECOMMENDED_LISTS.find(l => l.url === url)
    if (rec) return rec.label
    try {
      const u = new URL(url)
      const parts = u.pathname.split('/')
      return parts[parts.length - 1] || u.hostname
    } catch { return url }
  }
</script>

<SettingsSection
  title="Network"
  description="Pi-hole local DNS aliases and ad/tracker blocklists. Hidden if Pi-hole isn't reachable."
  icon={Network}
>
  {#if !piholeAvailable && dnsHosts === null && blocklists === null}
    <p class="muted">Pi-hole not detected. Set <code>PIHOLE_API_URL</code> + <code>PIHOLE_API_KEY</code> in <code>.env</code> to enable.</p>
  {:else}
    <SettingGroup title="Local DNS" hint="Friendly hostnames for the apartment network. Added directly to Pi-hole's local DNS records.">
      {#if dnsHosts && dnsHosts.length > 0}
        <div class="rows">
          {#each dnsHosts as record (record.ip + record.hostname)}
            <DnsHostRow {record} onDelete={deleteDnsHost} disabled={saving === 'dns-del'} />
          {/each}
        </div>
      {:else if dnsHosts}
        <p class="empty">No custom DNS records yet.</p>
      {/if}

      <div class="add-form">
        <input
          type="text"
          class="form-input"
          placeholder="hostname.lan"
          bind:value={newDnsHostname}
        />
        <input
          type="text"
          class="form-input form-input-sm"
          placeholder="192.168.1.x"
          bind:value={newDnsIp}
        />
        <SettingButton
          variant="ghost"
          disabled={!newDnsHostname || !newDnsIp || saving === 'dns-add'}
          loading={saving === 'dns-add'}
          on:click={addDnsHost}
        >Add</SettingButton>
      </div>

      <div class="defaults-row">
        <SettingButton variant="accent" loading={saving === 'dns-defaults'} on:click={addAllDefaultDns}>
          {saving === 'dns-defaults' ? 'Adding…' : 'Seed apartment devices'}
        </SettingButton>
        <span class="muted-mini">homehub · pihole · hue · sonos · desktop · tablet</span>
      </div>
    </SettingGroup>

    <SettingGroup title="Blocklists" hint="Ad / tracker / malware DNS filters. Pi-hole refreshes its blocklist gravity once per day.">
      {#if blocklists && blocklists.length > 0}
        <div class="rows">
          {#each blocklists as list (list.address)}
            <BlocklistRow {list} label={getListLabel(list.address)} onDelete={deleteBlocklist} disabled={saving === 'list-del'} />
          {/each}
        </div>
      {:else if blocklists}
        <p class="empty">No blocklists configured.</p>
      {/if}

      <div class="add-form">
        <input
          type="url"
          class="form-input form-input-wide"
          placeholder="https://blocklist-url..."
          bind:value={newBlocklistUrl}
        />
        <SettingButton
          variant="ghost"
          disabled={!newBlocklistUrl || saving === 'list-add'}
          loading={saving === 'list-add'}
          on:click={() => addBlocklist(newBlocklistUrl)}
        >Add</SettingButton>
      </div>

      <div class="defaults-row">
        <SettingButton variant="accent" loading={saving === 'lists-recommended'} on:click={addAllRecommendedLists}>
          {saving === 'lists-recommended' ? 'Adding…' : 'Seed curated lists'}
        </SettingButton>
        <span class="muted-mini">{RECOMMENDED_LISTS.length} lists · ads, malware, tracking, phishing</span>
      </div>
    </SettingGroup>

    {#if allowDomains !== null}
      <SettingGroup title="Allowlist" hint="Domains to never block — your safety net for false positives, like an email “click” link a blocklist caught. A bulk functionality allowlist is also subscribed directly on Pi-hole.">
        {#if allowDomains.length > 0}
          <div class="rows">
            {#each allowDomains as entry (entry.domain)}
              <div class="allow-row">
                <span class="allow-domain">{entry.domain}</span>
                {#if entry.comment}<span class="allow-comment">{entry.comment}</span>{/if}
                <button
                  class="allow-del"
                  disabled={saving === 'allow-del'}
                  on:click={() => deleteAllowDomain(entry.domain)}
                  aria-label={`Remove ${entry.domain} from allowlist`}
                >×</button>
              </div>
            {/each}
          </div>
        {:else}
          <p class="empty">No individually-allowed domains yet.</p>
        {/if}

        <div class="add-form">
          <input
            type="text"
            class="form-input form-input-wide"
            placeholder="click.email-example.com"
            bind:value={newAllowDomain}
          />
          <SettingButton
            variant="ghost"
            disabled={!newAllowDomain || saving === 'allow-add'}
            loading={saving === 'allow-add'}
            on:click={addAllowDomain}
          >Allow</SettingButton>
        </div>
      </SettingGroup>
    {/if}
  {/if}
</SettingsSection>

<style>
  .muted {
    margin: 0;
    font-family: var(--font-body);
    font-size: 13px;
    color: var(--text-muted);
    line-height: 1.6;
  }

  .muted code {
    background: rgba(255, 255, 255, 0.06);
    padding: 1px 6px;
    border-radius: 4px;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 11px;
    color: var(--text-primary);
  }

  .rows {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .empty {
    margin: 0;
    padding: 12px 4px;
    font-family: var(--font-body);
    font-size: 12px;
    color: var(--text-muted);
  }

  .add-form {
    display: flex;
    gap: 8px;
    margin-top: 4px;
  }

  .form-input {
    flex: 1;
    min-width: 0;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-primary);
    font-family: var(--font-body);
    font-size: 13px;
    outline: none;
    transition: border-color 0.18s;
  }

  .form-input:focus {
    border-color: var(--accent);
  }

  .form-input::placeholder {
    color: var(--text-muted);
  }

  .form-input-sm {
    flex: 0.6;
  }

  .form-input-wide {
    flex: 2;
  }

  .defaults-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 6px;
  }

  .allow-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.03);
  }

  .allow-domain {
    flex: 0 1 auto;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 12px;
    color: var(--text-primary);
    word-break: break-all;
  }

  .allow-comment {
    flex: 1;
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
  }

  .allow-del {
    flex: 0 0 auto;
    margin-left: auto;
    width: 24px;
    height: 24px;
    display: grid;
    place-items: center;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: transparent;
    color: var(--text-muted);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    transition: color 0.18s, border-color 0.18s;
  }

  .allow-del:hover:not(:disabled) {
    color: var(--text-primary);
    border-color: var(--accent);
  }

  .allow-del:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .muted-mini {
    font-family: var(--font-body);
    font-size: 11px;
    color: var(--text-muted);
    line-height: 1.4;
  }

  @media (max-width: 540px) {
    .add-form {
      flex-wrap: wrap;
    }
    .form-input-sm,
    .form-input-wide {
      flex: 1 1 100%;
    }
  }
</style>
