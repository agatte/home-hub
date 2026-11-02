<script>
  // Read-only source-qualified report: REST receipt is not sensor/room/causal evidence.
  import { onMount } from 'svelte'
  import { connected } from '$lib/stores/connection.js'
  import {
    newHomeContextSnapshot, homeContextConnectionChanged, invalidateHomeContextRead,
    beginHomeContextRead, acceptHomeContextRead, failHomeContextRead, homeContextPresentation,
  } from '$lib/quietAtlas/homeContextSnapshot.js'

  let snapshot = newHomeContextSnapshot()
  let nowMs = 0
  $: report = homeContextPresentation(snapshot, nowMs)

  onMount(() => {
    let mounted = true
    /** @type {AbortController | null} */
    let controller = null
    let failures = 0
    let nextPollAt = 0

    function abortRead() {
      controller?.abort()
      controller = null
    }

    async function refresh() {
      if (!mounted || !snapshot.connected || document.visibilityState !== 'visible') return
      const next = beginHomeContextRead(snapshot)
      snapshot = next.state
      if (!next.ticket) return
      const ticket = next.ticket
      controller = new AbortController()
      const current = controller
      const timeout = window.setTimeout(() => current.abort(), 8000)
      nextPollAt = Date.now() + 30000
      try {
        const response = await fetch('/api/automation/status', {
          signal: current.signal, cache: 'no-store',
        })
        if (!response.ok) throw new Error('HomeHub status unavailable')
        const body = await response.json()
        if (!mounted) return
        const receivedAt = Date.now()
        const accepted = acceptHomeContextRead(snapshot, ticket, body, receivedAt)
        if (accepted !== snapshot) {
          snapshot = accepted
          nowMs = receivedAt
          failures = accepted.failed ? Math.min(3, failures + 1) : 0
          nextPollAt = receivedAt + (accepted.failed ? Math.min(120000, 15000 * 2 ** failures) : 30000)
        }
      } catch {
        if (!mounted) return
        const failed = failHomeContextRead(snapshot, ticket)
        if (failed !== snapshot) {
          snapshot = failed
          nowMs = Date.now()
          failures = Math.min(3, failures + 1)
          nextPollAt = nowMs + Math.min(120000, 15000 * 2 ** failures)
        }
      } finally {
        window.clearTimeout(timeout)
        if (controller === current) controller = null
      }
    }

    function connectionChanged(available) {
      if (!mounted) return
      abortRead()
      const wasConnected = snapshot.connected
      snapshot = homeContextConnectionChanged(snapshot, available)
      nowMs = Date.now()
      if (available && !wasConnected && document.visibilityState === 'visible') {
        failures = 0
        nextPollAt = 0
        void refresh()
      }
    }

    function visibilityChanged() {
      if (!mounted) return
      abortRead()
      snapshot = invalidateHomeContextRead(snapshot)
      nowMs = Date.now()
      if (document.visibilityState === 'visible' && snapshot.connected) {
        nextPollAt = 0
        void refresh()
      }
    }

    const unsubscribe = connected.subscribe(connectionChanged)
    document.addEventListener('visibilitychange', visibilityChanged)
    const ageTimer = window.setInterval(() => { nowMs = Date.now() }, 1000)
    const pollTimer = window.setInterval(() => {
      if (snapshot.connected && !snapshot.pending && document.visibilityState === 'visible' &&
          Date.now() >= nextPollAt) void refresh()
    }, 15000)
    return () => {
      mounted = false
      abortRead()
      snapshot = invalidateHomeContextRead(snapshot)
      unsubscribe()
      document.removeEventListener('visibilitychange', visibilityChanged)
      window.clearInterval(ageTimer)
      window.clearInterval(pollTimer)
    }
  })
</script>

<section class="context-readout" aria-labelledby="insights-context-title" data-status={report.status}>
  <div class="context-caption">
    <div>
      <p class="context-eyebrow">CURRENT / SOURCE-QUALIFIED</p>
      <h2 id="insights-context-title">HomeHub reports</h2>
    </div>
    <span class="context-status" role="status">
      {report.status === 'recent' ? 'RECENT REST REPORT' : 'CONTEXT NOT VERIFIED'}
    </span>
  </div>
  <div class="context-values">
    <div class="context-value"><span>HOUSE STATE</span><strong>{report.house}</strong></div>
    <div class="context-value"><span>ACTIVITY</span><strong>{report.activity}</strong></div>
  </div>
  <p class="context-note">{report.note}. REST receipt is not source-sensor freshness, proof of a person, a physical room, or why automation acted.</p>
</section>

<style>
  .context-readout { border-top:1px solid rgba(201,218,200,.22);border-bottom:1px solid rgba(201,218,200,.17);margin:0 0 clamp(36px,5vw,60px);padding:clamp(20px,3vw,28px) 0;max-width:1460px;color:#e8ece3; }
  .context-caption {display:flex;gap:16px;justify-content:space-between;align-items:flex-start;}
  .context-eyebrow {margin:0 0 9px;color:#aec2af;font-size:10px;font-weight:700;letter-spacing:.16em;}
  h2 {margin:0;font:400 clamp(23px,3vw,33px)/1.2 Georgia,"Times New Roman",serif;letter-spacing:-.02em;}
  .context-status {color:#dec495;border:1px solid rgba(222,196,149,.32);border-radius:3px;font-size:10px;font-weight:650;letter-spacing:.07em;padding:7px 9px;}
  .context-values {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:clamp(18px,3vw,34px);max-width:700px;margin:24px 0 16px;}
  .context-value {display:flex;flex-direction:column;gap:7px;min-width:0;}
  .context-value span {color:#a6b9aa;font-size:10px;letter-spacing:.13em;font-weight:700;}
  .context-value strong {font:400 clamp(25px,3.4vw,39px)/1.14 Georgia,"Times New Roman",serif;overflow-wrap:anywhere;}
  .context-note {color:#a6b9aa;max-width:800px;margin:0;font-size:11px;line-height:1.7;}
  .context-readout:not([data-status="recent"]) .context-value strong {color:#acb8a9;}
  @media(max-width:480px){.context-caption{flex-direction:column;gap:12px}.context-status{align-self:flex-start}.context-values{gap:14px;margin:18px 0 15px}.context-value strong{font-size:clamp(21px,6.2vw,28px)}}
</style>
