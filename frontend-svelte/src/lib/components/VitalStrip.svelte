<script>
  import { onMount, onDestroy } from 'svelte'
  import { apiGet } from '$lib/api.js'
  import { Activity, Cpu, HardDrive, MemoryStick, Radio, Shield, Thermometer, Wifi } from 'lucide-svelte'

  const POLL_MS = 30_000

  /** @type {any} */
  let vitals = null
  let collapsed = true
  /** @type {ReturnType<typeof setInterval> | null} */
  let timer = null

  async function refresh() {
    try {
      vitals = await apiGet('/api/vitals')
    } catch {
      vitals = { status: 'error', metrics: {} }
    }
  }

  onMount(() => {
    refresh()
    timer = setInterval(refresh, POLL_MS)
  })

  onDestroy(() => {
    if (timer) clearInterval(timer)
  })

  /** @param {string | undefined} status */
  function dotColor(status) {
    if (status === 'error') return '#e25c5c'
    if (status === 'warn') return '#e0a64a'
    if (status === 'ok') return '#4dc28a'
    return 'rgba(255,255,255,0.35)'
  }

  $: m = vitals?.metrics ?? {}
  $: overall = vitals?.status ?? 'ok'
  $: chips = buildChips(m)

  /** @param {any} metrics */
  function buildChips(metrics) {
    /** @type {{key: string, label: string, value: string, status: string, icon: any}[]} */
    const out = []
    if (metrics.hue) {
      out.push({
        key: 'hue',
        label: 'Hue',
        value: metrics.hue.connected ? 'on' : 'off',
        status: metrics.hue.status,
        icon: Radio,
      })
    }
    if (metrics.sonos) {
      out.push({
        key: 'sonos',
        label: 'Sonos',
        value: metrics.sonos.connected ? 'on' : 'off',
        status: metrics.sonos.status,
        icon: Radio,
      })
    }
    if (metrics.fusion) {
      const c = metrics.fusion.confidence
      const v = c == null ? '—' : `${Math.round(c * 100)}%`
      out.push({
        key: 'fusion',
        label: 'ML',
        value: v,
        status: metrics.fusion.status,
        icon: Activity,
      })
    }
    if (metrics.pihole) {
      const blocked = metrics.pihole.blocked ?? 0
      out.push({
        key: 'pihole',
        label: 'PiHole',
        value: formatCount(blocked),
        status: metrics.pihole.status,
        icon: Shield,
      })
    }
    if (metrics.cpu_temp) {
      out.push({
        key: 'cpu',
        label: 'CPU',
        value: `${metrics.cpu_temp.celsius}°`,
        status: metrics.cpu_temp.status,
        icon: Thermometer,
      })
    }
    if (metrics.memory) {
      out.push({
        key: 'memory',
        label: 'Mem',
        value: `${metrics.memory.percent}%`,
        status: metrics.memory.status,
        icon: MemoryStick,
      })
    }
    if (metrics.disk) {
      out.push({
        key: 'disk',
        label: 'Disk',
        value: `${metrics.disk.percent}%`,
        status: metrics.disk.status,
        icon: HardDrive,
      })
    }
    if (typeof metrics.websocket_clients === 'number') {
      out.push({
        key: 'ws',
        label: 'WS',
        value: String(metrics.websocket_clients),
        status: 'ok',
        icon: Wifi,
      })
    }
    return out
  }

  /** @param {number} n */
  function formatCount(n) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
    return String(n)
  }
</script>

<div class="vital-strip" class:vital-strip-error={overall === 'error'} class:vital-strip-warn={overall === 'warn'}>
  <button
    type="button"
    class="vital-overall"
    class:vital-overall-collapsed={collapsed}
    on:click={() => (collapsed = !collapsed)}
    aria-label="Toggle vitals strip"
    title="Click to expand vitals"
  >
    <span class="vital-overall-dot" style="background: {dotColor(overall)}"></span>
  </button>

  {#if !collapsed}
    <div class="vital-chips">
      {#each chips as chip (chip.key)}
        <span class="vital-chip" title="{chip.label}: {chip.value} ({chip.status})">
          <span class="vital-chip-dot" style="background: {dotColor(chip.status)}"></span>
          <svelte:component this={chip.icon} size={11} strokeWidth={2.2} />
          <span class="vital-chip-label">{chip.label}</span>
          <span class="vital-chip-value">{chip.value}</span>
        </span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .vital-strip {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 22px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 10px;
    background: rgba(8, 8, 14, 0.72);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    backdrop-filter: blur(8px);
    z-index: 80;
    font-family: var(--font-body);
    font-size: 10.5px;
    color: rgba(255, 255, 255, 0.7);
    transition: background 0.3s, border-color 0.3s;
  }

  .vital-strip-warn {
    background: rgba(40, 28, 12, 0.78);
    border-top-color: rgba(224, 166, 74, 0.4);
  }

  .vital-strip-error {
    background: rgba(40, 12, 12, 0.85);
    border-top-color: rgba(226, 92, 92, 0.55);
  }

  .vital-overall {
    background: transparent;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    flex-shrink: 0;
  }

  .vital-overall-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    box-shadow: 0 0 6px currentColor;
  }

  .vital-overall-collapsed:hover .vital-overall-dot {
    transform: scale(1.2);
  }

  .vital-chips {
    display: flex;
    align-items: center;
    gap: 12px;
    overflow-x: auto;
    flex: 1;
    -ms-overflow-style: none;
    scrollbar-width: none;
  }

  .vital-chips::-webkit-scrollbar { display: none; }

  .vital-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .vital-chip-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .vital-chip-label {
    color: rgba(255, 255, 255, 0.45);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .vital-chip-value {
    color: rgba(255, 255, 255, 0.85);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }

  /* Mobile: overall-only stays out of the way; expanded chips scroll. */
  @media (max-width: 600px) {
    .vital-strip {
      font-size: 10px;
      gap: 6px;
    }

    .vital-chips {
      gap: 8px;
    }

    .vital-chip-label {
      display: none;
    }
  }
</style>
