<script>
  import { pipeline } from '$lib/stores/pipeline.js'
  import { modeColor, modeLabel, modeLucide } from '$lib/theme.js'
  import PipelineInputCard from './PipelineInputCard.svelte'
  import PipelineHistory from './PipelineHistory.svelte'

  /** Input metadata for display
   * @type {Record<string, { label: string, icon: string, priority: number }>} */
  const INPUT_META = {
    manual_override: { label: 'Manual Override', icon: 'hand', priority: 100 },
    activity:        { label: 'Activity',        icon: 'cpu',  priority: 50  },
    ambient:         { label: 'Ambient Noise',   icon: 'mic',  priority: 40  },
    screen_sync:     { label: 'Screen Sync',     icon: 'monitor-smartphone', priority: 30 },
    time_of_day:     { label: 'Time of Day',     icon: 'clock', priority: 20 },
    weather:         { label: 'Weather',          icon: 'cloud', priority: 15 },
    brightness:      { label: 'Brightness',       icon: 'sun',  priority: 10 },
    scene_override:  { label: 'Scene Override',   icon: 'palette', priority: 5 },
  }

  $: current = $pipeline.current
  $: history = $pipeline.history

  /** Get top 3 active inputs sorted by relevance */
  $: activeInputs = (() => {
    if (!current?.inputs) return []
    return Object.entries(current.inputs)
      .map(([key, val]) => ({
        key,
        ...val,
        ...INPUT_META[key],
        isWinner: current.resolution?.winning_input === key,
      }))
      .filter(i => i.active || i.applies || i.isWinner)
      .sort((a, b) => {
        // Winner first, then by priority
        if (a.isWinner && !b.isWinner) return -1
        if (!a.isWinner && b.isWinner) return 1
        return (b.priority || 0) - (a.priority || 0)
      })
      .slice(0, 3)
  })()

  $: effectiveMode = current?.resolution?.effective_mode || 'idle'
  $: mColor = modeColor(effectiveMode)

  /** Convert Hue HSB to CSS hsl for light preview circles
   * @param {any} light */
  function hueToCSS(light) {
    if (!light || !light.on) return 'rgba(255,255,255,0.05)'
    if (light.ct) {
      // CT mode — map mirek 153-500 to warm-cool
      const t = (light.ct - 153) / (500 - 153)
      const temp = Math.round(40 + (1 - t) * 40) // 40-80 hue range (warm-cool)
      const bri = Math.round((light.bri / 254) * 100)
      return `hsl(${temp}, 60%, ${Math.max(10, bri / 2)}%)`
    }
    // HSB mode
    const h = Math.round((light.hue / 65535) * 360)
    const s = Math.round((light.sat / 254) * 100)
    const l = Math.round((light.bri / 254) * 50)
    return `hsl(${h}, ${s}%, ${Math.max(8, l)}%)`
  }

  $: lights = current?.output?.lights || {}
  $: lightEntries = Object.entries(lights).sort(([a], [b]) => a.localeCompare(b))
</script>

<div class="pipeline">
  <!-- Active Inputs -->
  <section class="pipeline-section">
    <h3 class="section-label">ACTIVE INPUTS</h3>
    <div class="input-row">
      {#each activeInputs as input (input.key)}
        <PipelineInputCard {input} modeColor={mColor} />
      {/each}
      {#if activeInputs.length === 0}
        <div class="empty-state">No pipeline data yet</div>
      {/if}
    </div>
  </section>

  <!-- Connector Lines -->
  {#if current}
    <div class="connectors">
      <svg viewBox="0 0 300 40" preserveAspectRatio="none">
        {#each activeInputs as input, i}
          {@const x = activeInputs.length === 1 ? 150 : 50 + i * (200 / Math.max(1, activeInputs.length - 1))}
          <line
            x1={x} y1="0" x2="150" y2="40"
            stroke={input.isWinner ? mColor : 'rgba(255,255,255,0.1)'}
            stroke-width={input.isWinner ? 2 : 1}
            stroke-dasharray={input.isWinner ? 'none' : '4 4'}
          />
        {/each}
      </svg>
    </div>
  {/if}

  <!-- Priority Resolution -->
  <section class="pipeline-section">
    <h3 class="section-label">RESOLUTION</h3>
    {#if current?.resolution}
      <div class="resolution-card widget">
        <div class="resolution-winner">
          <span class="winner-dot" style="background: {mColor}"></span>
          <span class="winner-label">{INPUT_META[current.resolution.winning_input]?.label || current.resolution.winning_input}</span>
        </div>
        <p class="resolution-reason">{current.resolution.reason}</p>
        <div class="resolution-mode">
          <span class="mode-badge" style="background: {mColor}20; color: {mColor}; border: 1px solid {mColor}40">
            {modeLabel(effectiveMode)}
          </span>
        </div>
      </div>
    {:else}
      <div class="widget empty-state">Waiting for data...</div>
    {/if}
  </section>

  <!-- Connector Lines -->
  {#if current}
    <div class="connectors">
      <svg viewBox="0 0 300 30" preserveAspectRatio="none">
        <line x1="150" y1="0" x2="150" y2="30" stroke={mColor} stroke-width="2" />
      </svg>
    </div>
  {/if}

  <!-- Final Output -->
  <section class="pipeline-section">
    <h3 class="section-label">OUTPUT</h3>
    {#if current?.output}
      <div class="output-card widget">
        <div class="output-header">
          <span class="mode-badge large" style="background: {mColor}20; color: {mColor}; border: 1px solid {mColor}40">
            {modeLabel(current.output.mode)}
          </span>
          <span class="period-tag">{current.output.time_period}</span>
        </div>

        <div class="output-lights">
          <span class="lights-label">Lights</span>
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
            {#if lightEntries.length === 0}
              <span class="no-lights">No light data</span>
            {/if}
          </div>
        </div>

        {#if current.output.effect}
          <div class="output-detail">
            <span class="detail-label">Effect</span>
            <span class="detail-value">{current.output.effect}</span>
          </div>
        {/if}

        {#if current.output.social_style}
          <div class="output-detail">
            <span class="detail-label">Style</span>
            <span class="detail-value">{current.output.social_style}</span>
          </div>
        {/if}

        {#if current.output.brightness_multiplier && current.output.brightness_multiplier !== 1.0}
          <div class="output-detail">
            <span class="detail-label">Brightness</span>
            <span class="detail-value">{current.output.brightness_multiplier}x</span>
          </div>
        {/if}
      </div>
    {:else}
      <div class="widget empty-state">Waiting for data...</div>
    {/if}
  </section>

  <!-- Decision History -->
  {#if history.length > 0}
    <PipelineHistory {history} />
  {/if}
</div>

<style>
  .pipeline {
    display: flex;
    flex-direction: column;
    gap: 0;
    max-width: 600px;
    margin: 0 auto;
  }

  .pipeline-section {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .section-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 2px;
    color: rgba(255, 255, 255, 0.35);
    margin: 0;
    padding: 0 4px;
  }

  .input-row {
    display: flex;
    gap: 10px;
    justify-content: center;
  }

  .connectors {
    display: flex;
    justify-content: center;
    height: 30px;
    padding: 0 20px;
  }
  .connectors svg {
    width: 100%;
    max-width: 400px;
    height: 100%;
  }

  .resolution-card {
    text-align: center;
    padding: 16px 20px;
  }
  .resolution-winner {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-bottom: 8px;
  }
  .winner-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .winner-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 18px;
    letter-spacing: 1px;
    color: rgba(255, 255, 255, 0.9);
  }
  .resolution-reason {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.5);
    margin: 0 0 12px;
    line-height: 1.4;
  }
  .resolution-mode {
    display: flex;
    justify-content: center;
  }

  .mode-badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 14px;
    letter-spacing: 1.5px;
    transition: all 0.4s ease;
  }
  .mode-badge.large {
    font-size: 18px;
    padding: 6px 20px;
  }

  .output-card {
    padding: 20px;
  }
  .output-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }
  .period-tag {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.35);
    text-transform: uppercase;
    letter-spacing: 1px;
    font-family: 'Bebas Neue', sans-serif;
  }

  .output-lights {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }
  .lights-label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.35);
    text-transform: uppercase;
    letter-spacing: 1px;
    font-family: 'Bebas Neue', sans-serif;
    flex-shrink: 0;
  }
  .light-dots {
    display: flex;
    gap: 10px;
    flex: 1;
  }
  .light-dot-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .light-dot {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 2px solid rgba(255, 255, 255, 0.1);
    transition: background 0.6s ease, border-color 0.3s ease;
    box-shadow: 0 0 8px rgba(0, 0, 0, 0.3);
  }
  .light-dot:hover {
    border-color: rgba(255, 255, 255, 0.3);
  }
  .light-dot.off {
    opacity: 0.25;
  }
  .light-id {
    font-size: 10px;
    color: rgba(255, 255, 255, 0.3);
    font-family: 'Source Sans 3', sans-serif;
  }
  .no-lights {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.25);
  }

  .output-detail {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
  }
  .detail-label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.35);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  .detail-value {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.7);
    text-transform: capitalize;
  }

  .empty-state {
    text-align: center;
    padding: 24px;
    color: rgba(255, 255, 255, 0.3);
    font-size: 14px;
  }

  @media (max-width: 480px) {
    .input-row {
      flex-direction: column;
      align-items: center;
    }
    .connectors {
      display: none;
    }
  }
</style>
