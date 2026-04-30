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
      loadError = e?.message ?? 'Failed to load journal entries'
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
      loadError = e?.message ?? 'Regenerate failed'
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
      loadError = e?.message ?? 'Generate failed'
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
  <title>Apartment Logbook · Home Hub</title>
</svelte:head>

<div class="journal-shell">
  <aside class="journal-rail">
    <header class="rail-head">
      <h1>Logbook</h1>
      <button class="rail-action" on:click={generateYesterday} disabled={regenerating}>
        {regenerating ? '…' : 'Generate yesterday'}
      </button>
    </header>

    {#if entries.length === 0}
      <p class="rail-empty">
        No entries yet. The nightly job runs at 2am — or click <em>Generate yesterday</em>.
      </p>
    {:else}
      <ul class="rail-list">
        {#each entries as entry}
          <li>
            <button
              class="rail-item"
              class:rail-active={activeDate === entry.date}
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

  <article class="journal-page">
    {#if loadError}
      <div class="journal-error">{loadError}</div>
    {/if}

    {#if loading}
      <div class="journal-loading">Loading…</div>
    {:else if markdown}
      <div class="journal-toolbar">
        <button class="rail-action" on:click={regenerateActive} disabled={regenerating}>
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

<style>
  .journal-shell {
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 24px;
    min-height: 100vh;
    padding: 32px 24px 96px;
    box-sizing: border-box;
  }

  @media (max-width: 768px) {
    .journal-shell {
      grid-template-columns: 1fr;
    }
  }

  .journal-rail {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md, 14px);
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

  .rail-head h1 {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 22px;
    margin: 0;
    letter-spacing: 0.04em;
  }

  .rail-action {
    background: rgba(140, 100, 200, 0.22);
    border: 1px solid rgba(140, 100, 200, 0.45);
    color: var(--text-primary, #fff);
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .rail-action:hover:not(:disabled) {
    background: rgba(140, 100, 200, 0.34);
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
    border-color: rgba(140, 100, 200, 0.5);
    background: rgba(140, 100, 200, 0.12);
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
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md, 14px);
    padding: 32px 36px;
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
    color: #d57;
    font-size: 13px;
    margin-bottom: 12px;
  }

  .journal-loading,
  .journal-placeholder {
    color: var(--text-muted);
    font-size: 14px;
    line-height: 1.6;
  }
</style>
