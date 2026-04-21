<script>
  import { pipeline } from '$lib/stores/pipeline.js'
  import { modeColor, modeLabel } from '$lib/theme.js'

  let open = false

  function formatAgo(iso) {
    if (!iso) return ''
    const diff = (Date.now() - new Date(iso).getTime()) / 1000
    if (diff < 60)    return 'just now'
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  function formatTime(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', hour12: false,
      timeZone: 'America/Indiana/Indianapolis',
    })
  }

  function entryMode(entry) {
    return entry.fusion?.fused_mode || entry.resolution?.effective_mode || 'idle'
  }

  function entryDescription(entry) {
    if (entry.fusion) {
      const f = entry.fusion
      const conf = Math.round((f.fused_confidence ?? 0) * 100)
      const total = f.total_signals ?? Object.keys(f.signals || {}).length
      const agreeing = Object.values(f.signals || {}).filter((s) => s?.agrees).length
      return `${modeLabel(f.fused_mode)} (${conf}%) · ${agreeing}/${total} agree`
    }
    if (entry.resolution) {
      return `${modeLabel(entry.resolution.effective_mode)} via ${
        (entry.resolution.winning_input || '').replace(/_/g, ' ')
      }`.trim()
    }
    return 'State refresh'
  }

  $: history = $pipeline.history || []
  $: lastEntry = history.length ? history[history.length - 1] : null
  $: prevEntry = history.length >= 2 ? history[history.length - 2] : null

  /** Best-effort summary of the most recent state change. */
  $: summary = (() => {
    if (!lastEntry) return 'No signal activity yet'
    const mode = entryMode(lastEntry)
    const prevMode = prevEntry ? entryMode(prevEntry) : null
    if (prevMode && prevMode !== mode) {
      return `${modeLabel(prevMode)} → ${modeLabel(mode)}`
    }
    return modeLabel(mode)
  })()

  $: summaryColor = modeColor(lastEntry ? entryMode(lastEntry) : 'idle')
  $: ago = formatAgo(lastEntry?.timestamp)
  $: reversed = [...history].reverse()
</script>

<button
  class="strip"
  class:open
  type="button"
  on:click={() => (open = !open)}
  aria-expanded={open}
>
  <span class="chevron" class:open>▾</span>
  <span class="title">History</span>
  <span class="dot" style="background: {summaryColor}"></span>
  <span class="summary">{summary}</span>
  {#if ago}
    <span class="ago">{ago}</span>
  {/if}
</button>

{#if open}
  <div class="drawer">
    {#if reversed.length === 0}
      <div class="empty">No history yet — signals will accumulate here</div>
    {:else}
      <ul class="history-list">
        {#each reversed as entry, i (entry.timestamp + i)}
          {@const mode = entryMode(entry)}
          <li class="history-row">
            <span class="hdot" style="background: {modeColor(mode)}"></span>
            <span class="htime">{formatTime(entry.timestamp)}</span>
            <span class="hdesc">{entryDescription(entry)}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style>
  .strip {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 10px;
    padding: 10px 14px;
    font-family: 'Source Sans 3', sans-serif;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.55);
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
  }
  .strip:hover {
    background: rgba(255, 255, 255, 0.045);
    border-color: rgba(255, 255, 255, 0.1);
  }
  .strip.open {
    border-radius: 10px 10px 0 0;
    border-bottom-color: transparent;
  }

  .chevron {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.3);
    transition: transform 0.2s ease;
  }
  .chevron.open {
    transform: rotate(180deg);
  }
  .title {
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 2.5px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }
  .summary {
    flex: 1;
    text-align: left;
    color: rgba(255, 255, 255, 0.7);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ago {
    color: rgba(255, 255, 255, 0.35);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }

  .drawer {
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-top: none;
    border-radius: 0 0 10px 10px;
    background: rgba(255, 255, 255, 0.025);
    padding: 6px 14px 12px;
    animation: slideDown 250ms ease;
    overflow: hidden;
    max-height: 360px;
    overflow-y: auto;
  }
  @keyframes slideDown {
    from { max-height: 0;   opacity: 0; }
    to   { max-height: 360px; opacity: 1; }
  }

  .empty {
    color: rgba(255, 255, 255, 0.3);
    font-size: 12px;
    padding: 16px 0;
    text-align: center;
  }

  .history-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }
  .history-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    font-size: 13px;
  }
  .history-row:last-child { border-bottom: none; }

  .hdot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .htime {
    font-family: 'Source Sans 3', sans-serif;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.35);
    font-variant-numeric: tabular-nums;
    min-width: 44px;
    flex-shrink: 0;
  }
  .hdesc {
    color: rgba(255, 255, 255, 0.6);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
