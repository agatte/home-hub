<script>
  import { onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'

  /** @type {{date: string, size_bytes: number, modified_utc: string}[]} */
  let entries = []
  /** @type {string | null} */
  let activeDate = null
  /** @type {string} */
  let markdown = ''
  /** @type {string | null} */
  let loadError = null
  let loading = false
  let regenerating = false

  onMount(async () => {
    await loadEntries()
  })

  async function loadEntries() {
    try {
      const data = /** @type {any} */ (await apiGet('/api/journal/entries'))
      entries = data?.entries ?? []
      if (entries.length && !activeDate) {
        await selectDate(entries[0].date)
      }
    } catch (e) {
      loadError = e instanceof Error ? e.message : 'Failed to load journal entries'
    }
  }

  /** @param {string} date */
  async function selectDate(date) {
    loading = true
    loadError = null
    activeDate = date
    try {
      const data = /** @type {any} */ (await apiGet(`/api/journal/${date}`))
      markdown = data?.markdown ?? ''
    } catch (e) {
      loadError = `No entry for ${date}`
      markdown = ''
    } finally {
      loading = false
    }
  }

  async function regenerateActive() {
    if (!activeDate) return
    regenerating = true
    try {
      await apiPost(`/api/journal/generate/${activeDate}`)
      await selectDate(activeDate)
      await loadEntries()
    } catch (e) {
      loadError = e instanceof Error ? e.message : 'Regenerate failed'
    } finally {
      regenerating = false
    }
  }

  async function generateYesterday() {
    const d = new Date()
    d.setDate(d.getDate() - 1)
    const iso = d.toISOString().slice(0, 10)
    regenerating = true
    try {
      await apiPost(`/api/journal/generate/${iso}`)
      await loadEntries()
      await selectDate(iso)
    } catch (e) {
      loadError = e instanceof Error ? e.message : 'Generate failed'
    } finally {
      regenerating = false
    }
  }

  /**
   * Tiny markdown renderer for the journal output. The journal generator
   * controls the input format (see backend/services/journal_service.py)
   * so we don't need a full CommonMark parser.
   * @param {string} text
   */
  function renderMarkdown(text) {
    if (!text) return ''
    const lines = text.split(/\r?\n/)
    /** @type {string[]} */
    const out = []
    /** @type {boolean} */
    let inList = false
    const flushList = () => {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
    }
    const inline = (/** @type {string} */ s) =>
      escapeHtml(s)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|\s)_([^_]+)_(\s|$|[.,;!?])/g, '$1<em>$2</em>$3')
    for (const raw of lines) {
      const line = raw
      if (!line.trim()) { flushList(); continue }
      const m1 = line.match(/^# (.+)$/)
      const m2 = line.match(/^## (.+)$/)
      const ml = line.match(/^- (.+)$/)
      if (m1) {
        flushList()
        out.push(`<h1>${inline(m1[1])}</h1>`)
      } else if (m2) {
        flushList()
        out.push(`<h2>${inline(m2[1])}</h2>`)
      } else if (ml) {
        if (!inList) { out.push('<ul>'); inList = true }
        out.push(`<li>${inline(ml[1])}</li>`)
      } else {
        flushList()
        out.push(`<p>${inline(line)}</p>`)
      }
    }
    flushList()
    return out.join('\n')
  }

  /** @param {string} s */
  function escapeHtml(s) {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }

  /** @param {string} iso */
  function formatDateLabel(iso) {
    const d = new Date(`${iso}T00:00:00`)
    return d.toLocaleDateString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
    })
  }

  /** @param {number} bytes */
  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes}B`
    return `${(bytes / 1024).toFixed(1)}KB`
  }
</script>

<svelte:head>
  <title>Activity journal | HomeHub</title>
</svelte:head>

<main class="journal-workspace" aria-label="HomeHub activity journal">
  <header class="workspace-head">
    <p class="eyebrow">HOMEHUB / HISTORY</p>
    <h1>Activity journal</h1>
    <p>Daily generated summaries of the apartment's recorded activity. These are summaries, not independent confirmation of presence or events.</p>
  </header>
  <div class="journal-shell">
  <aside class="journal-rail" aria-label="Journal dates">
    <header class="rail-head">
      <h2>Logbook</h2>
      <button type="button" class="rail-action" on:click={generateYesterday} disabled={regenerating || loading}>
        {regenerating ? '…' : 'Generate yesterday'}
      </button>
    </header>

    {#if entries.length === 0}
      <p class="rail-empty">
        No entries loaded. The nightly job is scheduled for 2am; you can also use <em>Generate yesterday</em>.
      </p>
    {:else}
      <div class="phone-date">
        <label for="journal-date">Choose an entry</label>
        <select id="journal-date" value={activeDate || ''} disabled={loading || regenerating} on:change={(event) => selectDate(event.currentTarget.value)}>
          {#each entries as entry (entry.date)}
            <option value={entry.date}>{formatDateLabel(entry.date)} · {entry.date}</option>
          {/each}
        </select>
      </div>
      <ul class="rail-list">
        {#each entries as entry}
          <li>
            <button
              class="rail-item"
              class:rail-active={activeDate === entry.date}
              type="button"
              aria-current={activeDate === entry.date ? 'date' : undefined}
              disabled={loading || regenerating}
              on:click={() => selectDate(entry.date)}
            >
              <span class="rail-date">{formatDateLabel(entry.date)}</span>
              <span class="rail-meta">{entry.date} · {formatSize(entry.size_bytes)}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <article class="journal-page" aria-busy={loading || regenerating}>
    {#if loadError}
      <div class="journal-error" role="status">{loadError}</div>
    {/if}

    {#if loading}
      <div class="journal-loading">Loading…</div>
    {:else if markdown}
      <div class="journal-toolbar">
        <button type="button" class="rail-action" on:click={regenerateActive} disabled={regenerating || loading}>
          {regenerating ? 'Regenerating…' : 'Regenerate'}
        </button>
      </div>
      <div class="journal-content">
        {@html renderMarkdown(markdown)}
      </div>
    {:else if entries.length > 0 && !loadError}
      <p class="journal-placeholder">Pick a date.</p>
    {:else}
      <p class="journal-placeholder">
        The Apartment Logbook writes a daily summary at 2am — patterns of light,
        music, and mode emerging across the week.
      </p>
    {/if}
  </article>
  </div>
</main>

<style>
  .journal-workspace {max-width:1440px;min-width:0;margin:0 auto;padding:clamp(18px,3vw,42px) var(--hh-gutter) 44px;color:var(--hh-ink);--text-primary:var(--hh-ink);--text-muted:var(--hh-muted);--font-body:var(--hh-font);--font-display:var(--hh-display);}
  .workspace-head {display:grid;gap:8px;margin-bottom:24px;}
  .workspace-head .eyebrow {font-size:11px;letter-spacing:.14em;font-weight:750;color:var(--hh-accent);}
  .workspace-head h1 {font:500 clamp(36px,5vw,60px)/1.1 var(--hh-display);letter-spacing:-.04em;}
  .workspace-head p:not(.eyebrow) {font-size:14px;line-height:1.6;color:var(--hh-muted);}
  .phone-date {display:none;}
  .journal-shell {
    display: grid;
    grid-template-columns: minmax(220px,280px) minmax(0,1fr);
    gap: 24px;
    min-width: 0;
    box-sizing: border-box;
  }

  @media (max-width: 1000px) {
    .journal-shell {
      grid-template-columns: minmax(0,1fr);
    }
  }

  .journal-rail {
    background: var(--hh-card-background);
    border: 1px solid var(--hh-line);
    border-radius: var(--hh-radius-panel);
    padding: 16px;
    backdrop-filter: blur(10px);
    align-self: start;
    position: sticky;
    top: 24px;
  }

  .rail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 12px;
  }

  .rail-head h2 {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
  }

  .rail-action {
    background: var(--hh-control);
    border: 1px solid var(--hh-line);
    color: var(--text-primary, #fff);
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .rail-action:hover:not(:disabled) {
    background: var(--hh-control-hover);
  }

  .rail-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .rail-empty {
    color: var(--text-muted);
    font-size: 13px;
    line-height: 1.5;
  }

  .rail-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: calc(100vh - 180px);
    overflow-y: auto;
  }

  .rail-item {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    color: var(--text-primary, #fff);
    padding: 10px 12px;
    border-radius: var(--radius-sm, 8px);
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .rail-item:hover {
    border-color: rgba(255, 255, 255, 0.1);
    background: rgba(255, 255, 255, 0.03);
  }

  .rail-active {
    border-color: var(--hh-accent);
    background: var(--hh-control);
  }

  .rail-date {
    font-size: 14px;
    font-weight: 600;
  }

  .rail-meta {
    font-size: 11px;
    color: var(--text-muted);
  }

  .journal-page {
    background: var(--hh-card-background);
    border: 1px solid var(--hh-line);
    border-radius: var(--hh-radius-panel);
    min-width:0;overflow-wrap:anywhere;
    padding: clamp(16px,3vw,36px);
    backdrop-filter: blur(10px);
    min-height: 60vh;
  }

  .journal-toolbar {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 16px;
  }

  .journal-content :global(h1) {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 36px;
    letter-spacing: 0.03em;
    margin: 0 0 24px;
  }

  .journal-content :global(h2) {
    font-family: var(--font-body);
    font-size: 17px;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: var(--text-muted);
    margin: 32px 0 12px;
  }

  .journal-content :global(p) {
    margin: 0 0 12px;
    line-height: 1.65;
    font-size: 15px;
  }

  .journal-content :global(ul) {
    margin: 0 0 16px;
    padding-left: 22px;
    line-height: 1.65;
    font-size: 15px;
  }

  .journal-content :global(li) {
    margin-bottom: 6px;
  }

  .journal-content :global(strong) {
    color: var(--text-primary, #fff);
    font-weight: 600;
  }

  .journal-content :global(em) {
    color: var(--text-muted);
    font-style: italic;
  }

  .journal-error {
    color: #f5a9a9;
    font-size: 13px;
    margin-bottom: 12px;
  }

  .journal-loading,
  .journal-placeholder {
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1.6;
  }
  .rail-action,.rail-item {min-height:44px;}
  .rail-action:focus-visible,.rail-item:focus-visible,.phone-date select:focus-visible {outline:3px solid var(--hh-focus);outline-offset:2px;}
  .rail-item:disabled {cursor:not-allowed;opacity:.65;}
  @media(max-width:1000px) {.journal-rail{position:static;}.rail-list{display:none;}.phone-date{display:grid;gap:8px;min-width:0;}.phone-date label{font-size:13px;color:var(--hh-muted);}.phone-date select{width:100%;min-width:0;min-height:48px;padding:8px 10px;background:var(--hh-control);border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);color:var(--hh-ink);font:inherit;font-size:16px;}}
  @media(max-width:600px) {.journal-workspace{padding:18px 16px 32px;}.journal-shell{gap:14px;}.rail-head{flex-wrap:wrap;}.journal-content :global(h1){font-size:28px;}.journal-content :global(h2){font-size:15px;letter-spacing:.06em;}}
  @media(prefers-reduced-motion:reduce) {.rail-action,.rail-item{transition:none;}}
</style>
