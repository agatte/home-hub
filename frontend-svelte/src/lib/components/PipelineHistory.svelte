<script>
  import { modeColor, modeLabel } from '$lib/theme.js'

  /** @type {any[]} */
  export let history = []

  let expanded = false

  /** Format ISO timestamp as HH:MM
   * @param {string} iso */
  function formatTime(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'America/Indiana/Indianapolis',
    })
  }

  /** Format ISO timestamp as relative time
   * @param {string} iso */
  function formatAgo(iso) {
    if (!iso) return ''
    const diff = (Date.now() - new Date(iso).getTime()) / 1000
    if (diff < 60) return 'just now'
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  }

  /** Build display string for a history entry
   * @param {any} entry
   * @param {any} prev */
  function entryDescription(entry, prev) {
    // If fusion data is present, show fusion-style summary
    if (entry.fusion) {
      const f = entry.fusion
      const confPct = Math.round((f.fused_confidence ?? 0) * 100)
      const agreeCount = Object.values(f.signals || {}).filter(/** @param {any} s */ s => s?.agrees).length
      const total = f.total_signals ?? Object.keys(f.signals || {}).length
      return `${modeLabel(f.fused_mode)} (${confPct}%) \u00b7 ${agreeCount}/${total} agree`
    }

    // Fallback: old resolution-based description
    if (!prev) return 'Initial state'
    const parts = []
    if (entry.resolution?.effective_mode !== prev.resolution?.effective_mode) {
      parts.push(
        `${modeLabel(prev.resolution.effective_mode)} \u2192 ${modeLabel(entry.resolution.effective_mode)}`
      )
    }
    if (entry.resolution?.winning_input !== prev.resolution?.winning_input) {
      parts.push(`via ${entry.resolution.winning_input.replace('_', ' ')}`)
    }
    if (entry.output?.effect !== prev.output?.effect) {
      const eff = entry.output.effect || 'none'
      parts.push(`effect: ${eff}`)
    }
    return parts.length ? parts.join(' \u00b7 ') : 'State refreshed'
  }

  /** Get the mode for a history entry */
  function entryMode(entry) {
    if (entry.fusion) return entry.fusion.fused_mode || 'idle'
    return entry.resolution?.effective_mode || 'idle'
  }

  $: reversedHistory = [...history].reverse()
  $: displayHistory = expanded ? reversedHistory : reversedHistory.slice(0, 8)
</script>

<section class="history-section">
  <button class="history-toggle" on:click={() => expanded = !expanded}>
    <h3 class="section-label">HISTORY</h3>
    <span class="chevron" class:open={expanded}>&#9662;</span>
  </button>

  <div class="history-list widget" class:collapsed={!expanded && reversedHistory.length > 8}>
    {#each displayHistory as entry, i}
      {@const prev = reversedHistory[i + 1] || null}
      {@const mode = entryMode(entry)}
      <div class="history-row">
        <span class="history-dot" style="background: {modeColor(mode)}"></span>
        <span class="history-time">{entry.fusion ? formatTime(entry.timestamp) : formatAgo(entry.timestamp)}</span>
        <span class="history-desc">{entryDescription(entry, prev)}</span>
      </div>
    {/each}
    {#if reversedHistory.length === 0}
      <div class="history-row empty">No history yet</div>
    {/if}
  </div>

  {#if !expanded && reversedHistory.length > 8}
    <button class="show-more" on:click={() => expanded = true}>
      Show {reversedHistory.length - 8} more
    </button>
  {/if}
</section>

<style>
  .history-section {
    margin-top: 8px;
  }

  .history-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px;
    width: 100%;
  }
  .history-toggle:hover .section-label {
    color: rgba(255, 255, 255, 0.5);
  }

  .section-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 2px;
    color: rgba(255, 255, 255, 0.35);
    margin: 0;
    transition: color 0.2s ease;
  }

  .chevron {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.25);
    transition: transform 0.2s ease;
  }
  .chevron.open {
    transform: rotate(180deg);
  }

  .history-list {
    padding: 8px 16px;
    max-height: 400px;
    overflow-y: auto;
  }
  .history-list.collapsed {
    max-height: none;
  }

  .history-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }
  .history-row:last-child {
    border-bottom: none;
  }
  .history-row.empty {
    justify-content: center;
    color: rgba(255, 255, 255, 0.25);
    font-size: 13px;
  }

  .history-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    transition: background 0.3s ease;
  }

  .history-time {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.3);
    min-width: 55px;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }

  .history-desc {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.55);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .show-more {
    display: block;
    width: 100%;
    padding: 8px;
    margin-top: 4px;
    background: none;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    color: rgba(255, 255, 255, 0.35);
    font-size: 12px;
    cursor: pointer;
    transition: color 0.2s, border-color 0.2s;
  }
  .show-more:hover {
    color: rgba(255, 255, 255, 0.6);
    border-color: rgba(255, 255, 255, 0.12);
  }
</style>
