<script>
  import { onMount } from 'svelte'
  import { apiGet } from '$lib/api.js'

  /** @type {string} */
  let markdown = ''
  /** @type {string | null} */
  let entryDate = null
  /** @type {boolean} */
  let isToday = false
  /** @type {string | null} */
  let loadError = null
  let loading = true

  onMount(async () => {
    try {
      const data = /** @type {any} */ (await apiGet('/api/analytics/digest/daily'))
      markdown = data?.markdown ?? ''
      entryDate = data?.date ?? null
      isToday = !!data?.is_today
    } catch (e) {
      // 404 is expected when no narrative has been generated yet — quiet fallback
      const msg = e?.message ?? 'Failed to load narrative'
      if (!String(msg).includes('404')) loadError = msg
    } finally {
      loading = false
    }
  })

  /**
   * Tiny markdown renderer for the analytics narrative.
   * Mirrors the journal renderer but adds *asterisk* italic support since the
   * narrator agent uses both styles.
   * @param {string} text
   */
  function renderMarkdown(text) {
    if (!text) return ''
    const lines = text.split(/\r?\n/)
    /** @type {string[]} */
    const out = []
    let inList = false
    const flushList = () => {
      if (inList) { out.push('</ul>'); inList = false }
    }
    /** @param {string} s */
    const inline = (s) =>
      escapeHtml(s)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
        .replace(/(^|\s)_([^_]+)_(\s|$|[.,;!?])/g, '$1<em>$2</em>$3')
    for (const raw of lines) {
      const line = raw
      const trimmed = line.trim()
      if (!trimmed) { flushList(); continue }
      if (trimmed === '---') { flushList(); out.push('<hr />'); continue }
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
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }

  /** @param {string | null} iso */
  function formatDateLabel(iso) {
    if (!iso) return ''
    const d = new Date(`${iso}T00:00:00`)
    return d.toLocaleDateString(undefined, {
      weekday: 'long', month: 'long', day: 'numeric',
    })
  }

  $: headingLabel = (() => {
    if (loading) return 'Narrative'
    if (!entryDate) return 'Narrative'
    if (isToday) return "Today's narrative"
    // Pull the most-recent stored narrative — typically yesterday, but
    // could be older if the agent hasn't run for a few days.
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    const yesterday = new Date(today.getTime() - 86400000)
    const entry = new Date(`${entryDate}T00:00:00`)
    if (entry.getTime() === yesterday.getTime()) return "Yesterday's narrative"
    return 'Recent narrative'
  })()
</script>

<section class="narrative-card">
  <header class="narrative-head">
    <div class="narrative-titles">
      <span class="narrative-eyebrow">{headingLabel}</span>
      {#if entryDate}
        <span class="narrative-subtitle">{formatDateLabel(entryDate)}</span>
      {/if}
    </div>
  </header>

  {#if loading}
    <p class="narrative-placeholder">Loading…</p>
  {:else if loadError}
    <p class="narrative-error">{loadError}</p>
  {:else if markdown}
    <div class="narrative-body">
      {@html renderMarkdown(markdown)}
    </div>
  {:else}
    <div class="narrative-empty">
      <p>No narrative written yet.</p>
      <p class="narrative-hint">
        Run <code>/analytics-narrator</code> in your assistant to generate one for yesterday,
        or <code>/analytics-narrator today</code> for an in-progress version of today.
      </p>
    </div>
  {/if}
</section>

<style>
  .narrative-card {
    background: rgba(20, 20, 32, 0.55);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: var(--radius-md, 14px);
    padding: 28px 32px;
    backdrop-filter: blur(10px);
  }

  .narrative-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 18px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding-bottom: 12px;
  }

  .narrative-titles {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .narrative-eyebrow {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 3px;
    color: rgba(255, 255, 255, 0.55);
    text-transform: uppercase;
  }

  .narrative-subtitle {
    font-size: 12px;
    color: var(--text-muted, rgba(255, 255, 255, 0.45));
  }

  .narrative-body :global(h1) {
    font-family: var(--font-display, 'Bebas Neue', sans-serif);
    font-size: 30px;
    letter-spacing: 0.03em;
    margin: 0 0 18px;
  }

  .narrative-body :global(h2) {
    font-family: var(--font-body);
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--text-muted, rgba(255, 255, 255, 0.5));
    margin: 24px 0 8px;
  }

  .narrative-body :global(p) {
    margin: 0 0 12px;
    line-height: 1.65;
    font-size: 15px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.85));
  }

  .narrative-body :global(ul) {
    margin: 0 0 16px;
    padding-left: 22px;
    line-height: 1.65;
    font-size: 14px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.85));
  }

  .narrative-body :global(li) {
    margin-bottom: 6px;
  }

  .narrative-body :global(strong) {
    color: var(--text-primary, #fff);
    font-weight: 600;
  }

  .narrative-body :global(em) {
    color: var(--text-muted, rgba(255, 255, 255, 0.55));
    font-style: italic;
  }

  .narrative-body :global(hr) {
    border: none;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    margin: 18px 0 8px;
  }

  .narrative-placeholder,
  .narrative-error,
  .narrative-empty {
    color: var(--text-muted, rgba(255, 255, 255, 0.45));
    font-size: 14px;
    line-height: 1.6;
  }

  .narrative-error {
    color: #d57;
  }

  .narrative-empty p {
    margin: 0 0 8px;
  }

  .narrative-hint {
    font-size: 13px;
    color: var(--text-muted, rgba(255, 255, 255, 0.4));
  }

  .narrative-hint code {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
  }
</style>
