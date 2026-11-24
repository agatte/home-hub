<script>
  import { onDestroy, onMount } from 'svelte'
  import { apiGet, apiPost } from '$lib/api.js'

  // Live mood vector + preview HSV. Polled every 5s while the page is
  // visible — short enough to feel live, long enough that the underlying
  // 2s camera cadence has time to refresh between polls.
  /** @type {{ vector: any, enabled: boolean, reason?: string, preview_hsv?: {hue: number, sat: number, bri: number} } | null} */
  let current = null

  /** @type {{ personality_enabled: boolean, emotion_enabled: boolean, desktop_emotion_enabled: boolean, mood_ring_enabled: boolean, mood_ring_light_id: string, calibration_bias: {valence: number, arousal: number, focus: number} } | null} */
  let settings = null

  /** @type {{count: number, samples: any[]} | null} */
  let history = null
  /** @type {{count: number, samples: any[]} | null} */
  let calHistory = null

  // Calibration form state — sliders start at the detector's last
  // reading (if any) so the user only nudges where they disagree.
  let selfV = 0
  let selfA = 0
  let selfF = 0.5
  let submitting = false
  let submitMsg = ''

  /** @type {ReturnType<typeof setInterval> | null} */
  let pollTimer = null

  async function loadCurrent() {
    try {
      current = /** @type {any} */ (await apiGet('/api/personality/mood/current'))
    } catch {
      // surfaced via error toast; keep last-known state
    }
  }

  async function loadSettings() {
    try {
      settings = /** @type {any} */ (await apiGet('/api/personality/settings'))
    } catch {}
  }

  async function loadHistory() {
    try {
      history = /** @type {any} */ (await apiGet('/api/personality/mood/history?hours=24'))
      calHistory = /** @type {any} */ (
        await apiGet('/api/personality/calibration/history?limit=20')
      )
    } catch {}
  }

  onMount(async () => {
    await Promise.all([loadCurrent(), loadSettings(), loadHistory()])
    pollTimer = setInterval(loadCurrent, 5000)
  })

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer)
  })

  async function toggleSetting(/** @type {string} */ key, /** @type {boolean} */ value) {
    try {
      const body = /** @type {Record<string, any>} */ ({})
      body[key] = value
      settings = /** @type {any} */ (await apiPost('/api/personality/settings', body))
    } catch {}
  }

  async function submitCalibration() {
    submitting = true
    submitMsg = ''
    try {
      const det = current?.vector
      const payload = {
        self_valence: selfV,
        self_arousal: selfA,
        self_focus: selfF,
        detected_valence: det?.valence ?? null,
        detected_arousal: det?.arousal ?? null,
        detected_focus: det?.focus ?? null,
        detected_confidence: det?.confidence ?? null,
      }
      const res = /** @type {any} */ (
        await apiPost('/api/personality/calibration', payload)
      )
      const bias = res?.bias
      if (bias?.fit) {
        submitMsg = `Bias refit on ${bias.samples_used} samples (V=${bias.valence.toFixed(2)} A=${bias.arousal.toFixed(2)} F=${bias.focus.toFixed(2)})`
      } else {
        submitMsg = `Saved (${bias?.samples_used ?? 0}/${10} until bias fit)`
      }
      await loadHistory()
      await loadSettings()
    } catch (e) {
      submitMsg = e instanceof Error ? e.message : 'Submit failed'
    } finally {
      submitting = false
    }
  }

  function snapToDetected() {
    const v = current?.vector
    if (!v) return
    selfV = v.valence
    selfA = v.arousal
    selfF = v.focus
  }

  // Hue API → CSS color for the preview swatch. Approximate; the real
  // lamp does CIE-space gamut clipping the bridge handles for us.
  /** @param {{hue: number, sat: number, bri: number} | null | undefined} hsv */
  function hsvToCss(hsv) {
    if (!hsv) return 'rgba(180,180,180,0.5)'
    const h = (hsv.hue / 65535) * 360
    const s = (hsv.sat / 254) * 100
    const v = 30 + (hsv.bri / 254) * 60  // visible-band lightness, never black
    return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${v.toFixed(0)}%)`
  }

  /** @param {number | null | undefined} n */
  function fmt(n) {
    if (n === null || n === undefined) return '—'
    return n.toFixed(2)
  }
</script>

<svelte:head><title>Personalization | HomeHub</title></svelte:head>

<main class="page" aria-label="HomeHub personalization">
  <header class="workspace-head">
    <p class="eyebrow">HOMEHUB / PREFERENCES</p>
    <h1>Personalization</h1>
    <p class="sub">Review HomeHub's experimental mood estimates, provide your own feedback and manage the existing personality settings.</p>
    <nav class="section-nav" aria-label="Personalization sections">
      <a href="#mood">Mood estimate</a><a href="#calibrate">Calibration</a><a href="#preferences">Preferences</a><a href="#history">History</a>
    </nav>
  </header>

  <!-- Live reading -->
  <div class="widget mood-widget" id="mood">
    <h2 class="widget-title">Latest reported mood estimate</h2>
    <p class="hint-block">Experimental model estimates may lag and are not proof of how you feel. The color swatch is a preview, not a physical lighting reading.</p>
    {#if !current}
      <p class="empty" role="status">No mood report available.</p>
    {:else if !current.enabled}
      <p class="empty">Emotion detection is off. Enable it in Settings below to start the shadow log.</p>
    {:else if !current.vector}
      <p class="empty">
        {current.reason === 'no_fresh_face'
          ? 'Camera is enabled but not detecting a confident face right now.'
          : 'Service is enabled but no reading is available.'}
      </p>
    {:else}
      <div class="reading">
        <div
          class="swatch"
          style="background: {hsvToCss(current.preview_hsv)}; box-shadow: 0 0 30px {hsvToCss(current.preview_hsv)};"
          title="Mood-ring color preview only"
        ></div>
        <div class="gauges">
          <div class="gauge">
            <span class="label">Valence</span>
            <span class="value">{fmt(current.vector.valence)}</span>
            <span class="hint">{current.vector.valence > 0 ? 'positive' : 'negative'}</span>
          </div>
          <div class="gauge">
            <span class="label">Arousal</span>
            <span class="value">{fmt(current.vector.arousal)}</span>
            <span class="hint">{current.vector.arousal > 0 ? 'energized' : 'calm'}</span>
          </div>
          <div class="gauge">
            <span class="label">Focus</span>
            <span class="value">{fmt(current.vector.focus)}</span>
            <span class="hint">{current.vector.focus > 0.6 ? 'locked in' : current.vector.focus > 0.4 ? 'neutral' : 'distracted'}</span>
          </div>
          <div class="gauge">
            <span class="label">Confidence</span>
            <span class="value">{fmt(current.vector.confidence)}</span>
            <span class="hint">face conf</span>
          </div>
        </div>
      </div>
      {#if current.vector.factors?.top_blendshapes?.length}
        <p class="factors">
          Top inputs:
          {#each current.vector.factors.top_blendshapes as bs, i}
            <code>{bs.name}={bs.value.toFixed(2)}</code>{#if i < current.vector.factors.top_blendshapes.length - 1},
            {/if}
          {/each}
        </p>
      {/if}
    {/if}
  </div>

  <!-- Calibration form -->
  <div class="widget" id="calibrate">
    <h2 class="widget-title">
      Calibrate
      <button class="ghost-btn" type="button" on:click={snapToDetected} disabled={!current?.vector}>
        Snap to detector
      </button>
    </h2>
    <p class="hint-block">
      Rate how you actually feel right now. After 10+ samples a per-axis bias is
      fit and added to live readings. Phase B (mood-ring light) only ships once
      detector vs self-report correlates at ρ &gt; 0.4 across 30 samples.
    </p>

    <div class="sliders">
      <label>
        <span>Valence ({selfV.toFixed(2)})</span>
        <input type="range" min="-1" max="1" step="0.05" bind:value={selfV} />
        <span class="ends"><em>negative</em><em>positive</em></span>
      </label>
      <label>
        <span>Arousal ({selfA.toFixed(2)})</span>
        <input type="range" min="-1" max="1" step="0.05" bind:value={selfA} />
        <span class="ends"><em>calm</em><em>energized</em></span>
      </label>
      <label>
        <span>Focus ({selfF.toFixed(2)})</span>
        <input type="range" min="0" max="1" step="0.05" bind:value={selfF} />
        <span class="ends"><em>distracted</em><em>locked in</em></span>
      </label>
    </div>

    <div class="submit-row">
      <button class="primary-btn" on:click={submitCalibration} disabled={submitting}>
        {submitting ? 'Saving…' : 'Save calibration'}
      </button>
      {#if submitMsg}<span class="submit-msg">{submitMsg}</span>{/if}
    </div>
  </div>

  <!-- Settings -->
  <div class="widget" id="preferences">
    <h2 class="widget-title">Personality preferences</h2>
    {#if settings}
      <div class="toggle-row">
        <label class="toggle">
          <input
            type="checkbox"
            checked={settings.personality_enabled}
            on:change={(e) => toggleSetting('personality_enabled', e.currentTarget.checked)}
          />
          <span><strong>Personality layer</strong> — master switch for emotion detection, mood-ring light, and the AI scene picker</span>
        </label>
        <label class="toggle" class:disabled={!settings.personality_enabled}>
          <input
            type="checkbox"
            checked={settings.emotion_enabled}
            disabled={!settings.personality_enabled}
            on:change={(e) => toggleSetting('emotion_enabled', e.currentTarget.checked)}
          />
          <span><strong>Emotion detection (Latitude)</strong> — face blendshapes via the Latitude webcam (requires the camera service to also be enabled)</span>
        </label>
        <label class="toggle" class:disabled={!settings.personality_enabled}>
          <input
            type="checkbox"
            checked={settings.desktop_emotion_enabled}
            disabled={!settings.personality_enabled}
            on:change={(e) => toggleSetting('desktop_emotion_enabled', e.currentTarget.checked)}
          />
          <span><strong>Emotion detection (desktop)</strong> — frontal blendshapes from the dev machine's webcam. Better geometry than the Latitude's living-room view (the desktop sees you head-on at the monitor); requires the Home Hub Agent Supervisor running on the desktop. Desktop wins when fresh; Latitude covers couch/relax moments.</span>
        </label>
        <label class="toggle" class:disabled={!settings.personality_enabled}>
          <input
            type="checkbox"
            checked={settings.mood_ring_enabled}
            disabled={!settings.personality_enabled}
            on:change={(e) => toggleSetting('mood_ring_enabled', e.currentTarget.checked)}
          />
          <span><strong>Mood-ring light</strong> — accent light reflects your mood vector (Phase B; no effect until shipped)</span>
        </label>
      </div>

      <div class="bias-readout">
        <span class="label">Current calibration bias:</span>
        <code>V {settings.calibration_bias.valence.toFixed(3)}</code>
        <code>A {settings.calibration_bias.arousal.toFixed(3)}</code>
        <code>F {settings.calibration_bias.focus.toFixed(3)}</code>
      </div>
    {:else}
      <p class="empty" role="status">No settings report available.</p>
    {/if}
  </div>

  <!-- History -->
  <div class="widget" id="history">
    <h2 class="widget-title">
      Last 24 Hours
      <span class="count">{history ? history.count + ' samples' : 'Unavailable'}</span>
    </h2>
    {#if history && history.samples.length}
      <div class="history-strip">
        {#each history.samples as s}
          {@const hsv = hsvToCss({
            hue: Math.round(((s.valence + 1) / 2) * 30000 + 5000),
            sat: Math.round(180 + s.confidence * 60),
            bri: Math.round(120 + s.arousal * 80),
          })}
          <div
            class="tick"
            style="background: {hsv}; height: {30 + s.focus * 30}px;"
            title={`${new Date(s.timestamp).toLocaleString()}\nV=${s.valence.toFixed(2)} A=${s.arousal.toFixed(2)} F=${s.focus.toFixed(2)} (conf=${s.confidence.toFixed(2)})`}
          ></div>
        {/each}
      </div>
    {:else if history}
      <p class="empty">No samples recorded yet.</p>
    {:else}
      <p class="empty" role="status">No history report available.</p>
    {/if}
    {#if calHistory && calHistory.count > 0}
      <p class="cal-count">Calibration samples submitted: <strong>{calHistory.count}</strong></p>
    {/if}
  </div>
</main>

<style>
  .page {
    max-width: 1080px;
    min-width:0;color:var(--hh-ink);--text-primary:var(--hh-ink);--text-muted:var(--hh-muted);--border:var(--hh-line);--accent:var(--hh-accent);--font-body:var(--hh-font);--font-display:var(--hh-display);
    margin: 0 auto;
    padding: clamp(18px,3vw,42px) var(--hh-gutter) 44px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .workspace-head {display:grid;gap:8px;}
  .eyebrow {font-size:11px;letter-spacing:.14em;font-weight:750;color:var(--hh-accent);}
  header h1 {font:500 clamp(36px,5vw,60px)/1.1 var(--hh-display);letter-spacing:-.04em;}
  header .sub {color:var(--hh-muted);font-size:14px;line-height:1.6;}
  .section-nav {display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;}
  .section-nav a {display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 12px;background:var(--hh-control);border:1px solid var(--hh-line);border-radius:var(--hh-radius-control);color:var(--hh-ink);text-decoration:none;font-size:13px;}
  .section-nav a:hover {background:var(--hh-control-hover);}
  .widget {
    min-width:0;overflow-wrap:anywhere;scroll-margin-top:80px;
    background: var(--hh-card-background);
    border: 1px solid var(--hh-line);
    border-radius: var(--hh-radius-panel);
    padding: 20px;
    backdrop-filter: blur(12px);
  }
  .widget-title {
    font-family: var(--hh-display);
    font-size: 24px;
    letter-spacing: 0;
    color: var(--text-primary);
    margin: 0 0 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .reading {
    display: grid;
    grid-template-columns: 120px minmax(0,1fr);
    gap: 18px;
    align-items: center;
  }
  .swatch {
    width: 120px;
    height: 120px;
    border-radius: 60px;
    border: 1px solid rgba(255, 255, 255, 0.15);
  }
  .gauges {
    display: grid;
    grid-template-columns: repeat(4, minmax(0,1fr));
    gap: 12px;
  }
  .gauge {
    display: flex;
    flex-direction: column;
  }
  .gauge .label {
    font-size: 10px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--text-muted);
  }
  .gauge .value {
    font-family: var(--font-display, 'Bebas Neue'), sans-serif;
    font-size: 28px;
    color: var(--text-primary);
    line-height: 1;
    margin: 4px 0 2px;
  }
  .gauge .hint {
    font-size: 11px;
    color: var(--text-muted);
  }
  .factors {
    margin-top: 14px;
    font-size: 11px;
    color: var(--text-muted);
  }
  .factors code {
    background: rgba(255, 255, 255, 0.04);
    padding: 1px 6px;
    border-radius: 4px;
    margin-right: 4px;
  }
  .empty {
    color: var(--text-muted);
    font-style: italic;
    margin: 8px 0;
  }
  .hint-block {
    color: var(--text-muted);
    font-size: 12px;
    margin: 0 0 16px;
  }
  .sliders {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .sliders label {
    display: grid;
    grid-template-columns: minmax(0,200px) minmax(0,1fr);
    align-items: center;
    gap: 12px;
  }
  .sliders label > span:first-child {
    font-size: 13px;
    color: var(--text-primary);
  }
  .sliders input[type='range'] {
    width: 100%;
  }
  .ends {
    grid-column: 2;
    display: flex;
    justify-content: space-between;
    color: var(--text-muted);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .submit-row {
    display: flex;
    gap: 12px;
    align-items: center;
    margin-top: 18px;
  }
  .primary-btn {
    padding: 8px 18px;
    border-radius: 8px;
    border: 1px solid var(--accent, #b78a52);
    background: var(--accent, #b78a52);
    color: #1a1a1a;
    font-weight: 600;
    letter-spacing: 1px;
    cursor: pointer;
    text-transform: uppercase;
    font-size: 12px;
  }
  .primary-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .ghost-btn {
    padding: 4px 12px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
  }
  .ghost-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
  .submit-msg {
    color: var(--text-muted);
    font-size: 12px;
  }
  .toggle-row {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .toggle {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    cursor: pointer;
  }
  .toggle.disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .toggle input {
    margin-top: 3px;
  }
  .toggle span {
    color: var(--text-primary);
    font-size: 13px;
    line-height: 1.5;
  }
  .bias-readout {
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }
  .bias-readout .label {
    color: var(--text-muted);
  }
  .bias-readout code {
    background: rgba(255, 255, 255, 0.04);
    padding: 2px 8px;
    border-radius: 4px;
    color: var(--text-primary);
  }
  .history-strip {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    height: 80px;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .tick {
    width: 6px;
    border-radius: 2px;
    flex-shrink: 0;
    opacity: 0.85;
  }
  .count {
    font-family: var(--font-body, 'Source Sans 3'), sans-serif;
    color: var(--text-muted);
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  .cal-count {
    margin-top: 12px;
    color: var(--text-muted);
    font-size: 12px;
  }

  /* Mobile: stack the slider rows and the reading card so nothing
     forces horizontal scroll at 390px. The 1280 kiosk surface keeps
     its side-by-side layout above the 640px breakpoint. */
  @media (max-width: 640px) {
    .sliders label {
      grid-template-columns: 1fr;
    }
    .ends {
      grid-column: 1;
    }
    .reading {
      grid-template-columns: 1fr;
      justify-items: center;
      text-align: center;
    }
    .gauges {
      grid-template-columns: repeat(2, minmax(0,1fr));
      gap: 16px;
    }
  }
  .mood-widget {background:radial-gradient(ellipse at 100% 0%,rgba(141,117,175,.09),transparent 65%),var(--hh-card-background);}
  .widget-title,.submit-row {flex-wrap:wrap;gap:10px;}
  .primary-btn,.ghost-btn {min-height:44px;white-space:normal;}
  .sliders input[type='range'] {min-width:0;min-height:44px;accent-color:var(--hh-accent);}
  .toggle {min-height:44px;align-items:center;}
  .toggle input {flex:0 0 auto;width:20px;height:20px;accent-color:var(--hh-accent);}
  .section-nav a:focus-visible,.primary-btn:focus-visible,.ghost-btn:focus-visible,.toggle input:focus-visible,.sliders input:focus-visible {outline:3px solid var(--hh-focus);outline-offset:2px;}
  @media(max-width:600px) {.page{padding:18px 16px 32px;}.widget{padding:16px;}.section-nav a{flex:1 1 auto;}.widget-title{font-size:21px;}.hint-block{line-height:1.55;}}
</style>
