<script>
  import { pipeline } from '$lib/stores/pipeline.js'
  import { modeColor, modeLabel } from '$lib/theme.js'
  import PipelineInputCard from './PipelineInputCard.svelte'
  import PipelineHistory from './PipelineHistory.svelte'

  $: current = $pipeline.current
  $: history = $pipeline.history

  // Fusion data
  $: fusion = current?.fusion || null
  $: fusedMode = fusion?.fused_mode || current?.resolution?.effective_mode || 'idle'
  $: mColor = modeColor(fusedMode)
  $: fusedConfidence = fusion?.fused_confidence ?? 0
  $: confPct = Math.round(fusedConfidence * 100)
  $: agreement = fusion?.agreement ?? 0
  $: activeSignals = fusion?.active_signals ?? 0
  $: totalSignals = fusion?.total_signals ?? 0
  $: signals = fusion?.signals || {}
  $: signalKeys = ['process', 'camera', 'audio_ml', 'rule_engine']

  // SVG arc math
  const RING_SIZE = 160
  const RING_RADIUS = 68
  const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS
  const RING_CENTER = RING_SIZE / 2

  $: arcOffset = RING_CIRCUMFERENCE * (1 - fusedConfidence)
  $: ringColor = confPct < 70 ? 'rgba(255,255,255,0.2)' : confPct < 90 ? '#f0a030' : '#30c060'
  $: ringPulse = confPct >= 95

  // Count agreeing signals
  $: agreeCount = Object.values(signals).filter(s => s?.agrees).length

  // Output section
  $: effectiveMode = current?.output?.mode || fusedMode
  $: timePeriod = current?.output?.time_period || ''
  $: lights = current?.output?.lights || {}
  $: lightEntries = Object.entries(lights).sort(([a], [b]) => a.localeCompare(b))

  /** Convert Hue HSB to CSS hsl for light preview circles
   * @param {any} light */
  function hueToCSS(light) {
    if (!light || !light.on) return 'rgba(255,255,255,0.05)'
    if (light.ct) {
      const t = (light.ct - 153) / (500 - 153)
      const temp = Math.round(40 + (1 - t) * 40)
      const bri = Math.round((light.bri / 254) * 100)
      return `hsl(${temp}, 60%, ${Math.max(10, bri / 2)}%)`
    }
    const h = Math.round((light.hue / 65535) * 360)
    const s = Math.round((light.sat / 254) * 100)
    const l = Math.round((light.bri / 254) * 50)
    return `hsl(${h}, ${s}%, ${Math.max(8, l)}%)`
  }
</script>

<div class="pipeline">
  {#if fusion}
    <!-- Fusion Score Ring -->
    <section class="fusion-header">
      <div class="ring-container">
        <svg
          width={RING_SIZE}
          height={RING_SIZE}
          viewBox="0 0 {RING_SIZE} {RING_SIZE}"
          class="fusion-ring"
          class:pulse={ringPulse}
        >
          <!-- Background track -->
          <circle
            cx={RING_CENTER}
            cy={RING_CENTER}
            r={RING_RADIUS}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            stroke-width="6"
          />
          <!-- Confidence arc -->
          <circle
            cx={RING_CENTER}
            cy={RING_CENTER}
            r={RING_RADIUS}
            fill="none"
            stroke={ringColor}
            stroke-width="6"
            stroke-linecap="round"
            stroke-dasharray={RING_CIRCUMFERENCE}
            stroke-dashoffset={arcOffset}
            transform="rotate(-90 {RING_CENTER} {RING_CENTER})"
            class="conf-arc"
          />
        </svg>
        <div class="ring-center-text">
          <span class="ring-pct">{confPct}</span>
          <span class="ring-pct-sign">%</span>
        </div>
      </div>

      <div class="fusion-meta">
        <span class="mode-badge" style="background: {mColor}20; color: {mColor}; border: 1px solid {mColor}40">
          {modeLabel(fusedMode)}
        </span>
        {#if timePeriod}
          <span class="period-tag">{timePeriod}</span>
        {/if}
        <span class="agreement-text">
          {agreeCount} of {totalSignals} signals agree
        </span>
      </div>
    </section>

    <!-- Signal Cards -->
    <section class="signals-section">
      <h3 class="section-label">SIGNALS</h3>
      <div class="signal-row">
        {#each signalKeys as key (key)}
          <PipelineInputCard
            source={key}
            signal={signals[key] || null}
            {fusedMode}
            {mColor}
          />
        {/each}
      </div>
    </section>
  {:else if current}
    <!-- Fallback: no fusion data, show old resolution info -->
    <section class="fusion-fallback widget">
      <p class="fallback-text">Fusion initializing...</p>
      {#if current.resolution}
        <div class="fallback-mode">
          <span class="mode-badge" style="background: {mColor}20; color: {mColor}; border: 1px solid {mColor}40">
            {modeLabel(current.resolution.effective_mode || 'idle')}
          </span>
          <span class="fallback-reason">{current.resolution.reason || ''}</span>
        </div>
      {/if}
    </section>
  {:else}
    <div class="empty-state">No pipeline data yet</div>
  {/if}

  <!-- Output -->
  {#if current?.output}
    <section class="output-section">
      <h3 class="section-label">OUTPUT</h3>
      <div class="output-card widget">
        <div class="output-row">
          <span class="mode-badge" style="background: {mColor}20; color: {mColor}; border: 1px solid {mColor}40">
            {modeLabel(current.output.mode)}
          </span>

          <div class="light-dots">
            {#each lightEntries as [id, state]}
              <div class="light-dot-wrap" title="Light {id}">
                <div
                  class="light-dot"
                  class:off={!state?.on}
                  style="background: {hueToCSS(state)}"
                ></div>
                <span class="light-id">L{id}</span>
              </div>
            {/each}
          </div>

          <div class="output-extras">
            {#if current.output.effect}
              <span class="output-tag">{current.output.effect}</span>
            {/if}
            {#if current.output.brightness_multiplier && current.output.brightness_multiplier !== 1.0}
              <span class="output-tag">{current.output.brightness_multiplier}x</span>
            {/if}
          </div>
        </div>
      </div>
    </section>
  {/if}

  <!-- History -->
  {#if history.length > 0}
    <PipelineHistory {history} />
  {/if}
</div>

<style>
  .pipeline {
    display: flex;
    flex-direction: column;
    gap: 20px;
    max-width: 700px;
    margin: 0 auto;
  }

  .section-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 2px;
    color: rgba(255, 255, 255, 0.35);
    margin: 0 0 10px;
    padding: 0 4px;
  }

  /* Fusion Ring */
  .fusion-header {
    display: flex;
    align-items: center;
    gap: 24px;
    justify-content: center;
    padding: 8px 0;
  }

  .ring-container {
    position: relative;
    width: 160px;
    height: 160px;
    flex-shrink: 0;
  }

  .fusion-ring {
    display: block;
  }

  .conf-arc {
    transition: stroke-dashoffset 0.6s ease, stroke 0.4s ease;
  }

  .fusion-ring.pulse .conf-arc {
    animation: ringPulse 2s ease-in-out infinite;
  }

  @keyframes ringPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
  }

  .ring-center-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    align-items: baseline;
    gap: 1px;
  }

  .ring-pct {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 42px;
    color: rgba(255, 255, 255, 0.9);
    line-height: 1;
    letter-spacing: -1px;
  }

  .ring-pct-sign {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 18px;
    color: rgba(255, 255, 255, 0.4);
  }

  .fusion-meta {
    display: flex;
    flex-direction: column;
    gap: 8px;
    align-items: flex-start;
  }

  .mode-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 16px;
    letter-spacing: 1.5px;
    transition: all 0.4s ease;
  }

  .period-tag {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.35);
    text-transform: uppercase;
    letter-spacing: 1px;
    font-family: 'Bebas Neue', sans-serif;
  }

  .agreement-text {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.4);
  }

  /* Signals */
  .signal-row {
    display: flex;
    gap: 10px;
    justify-content: center;
    flex-wrap: wrap;
  }

  /* Output */
  .output-card {
    padding: 16px 20px;
  }

  .output-row {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }

  .light-dots {
    display: flex;
    gap: 10px;
    flex: 1;
    min-width: 0;
  }

  .light-dot-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
  }

  .light-dot {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.1);
    transition: background 0.6s ease;
    box-shadow: 0 0 6px rgba(0, 0, 0, 0.3);
  }
  .light-dot.off {
    opacity: 0.25;
  }
  .light-id {
    font-size: 9px;
    color: rgba(255, 255, 255, 0.3);
    font-family: 'Source Sans 3', sans-serif;
  }

  .output-extras {
    display: flex;
    gap: 6px;
    align-items: center;
  }

  .output-tag {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.4);
    background: rgba(255, 255, 255, 0.06);
    padding: 2px 8px;
    border-radius: 8px;
    text-transform: capitalize;
  }

  /* Fallback */
  .fusion-fallback {
    text-align: center;
    padding: 24px;
  }
  .fallback-text {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.35);
    margin: 0 0 12px;
  }
  .fallback-mode {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
  }
  .fallback-reason {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.4);
  }

  .empty-state {
    text-align: center;
    padding: 32px;
    color: rgba(255, 255, 255, 0.3);
    font-size: 14px;
  }

  @media (max-width: 600px) {
    .fusion-header {
      flex-direction: column;
      gap: 12px;
    }
    .fusion-meta {
      align-items: center;
    }
    .signal-row {
      gap: 8px;
    }
    .output-row {
      flex-direction: column;
      align-items: flex-start;
      gap: 12px;
    }
  }
</style>
