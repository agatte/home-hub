<script>
  import { modeColor, modeColorSoft, modeLabel } from '$lib/theme.js'

  /** @type {{ nodes: any[], fusedMode: string, fusedConfidence: number }} */
  export let graph

  $: fusedMode = graph?.fusedMode || 'idle'
  $: fusedConf = Math.round((graph?.fusedConfidence || 0) * 100)
  $: lanes = (graph?.nodes || []).filter((n) => n.type === 'lane')
  $: factorsByLane = (() => {
    const byLane = {}
    for (const n of (graph?.nodes || [])) {
      if (n.type !== 'factor') continue
      if (!byLane[n.lane]) byLane[n.lane] = []
      byLane[n.lane].push(n)
    }
    return byLane
  })()
</script>

<section class="mobile">
  <!-- Hero — nucleus at top -->
  <div class="nucleus-row" style="--c: {modeColor(fusedMode)}; --halo: {modeColorSoft(fusedMode, 0.3)}">
    <div class="nucleus-disc">
      <div class="nucleus-label">{modeLabel(fusedMode).toUpperCase()}</div>
      <div class="nucleus-conf">{fusedConf}%</div>
    </div>
  </div>

  <!-- Stacked lane rows — weight as left-bar width -->
  <div class="lanes">
    {#each lanes as lane (lane.id)}
      {@const laneColor = lane.hasData ? modeColor(lane.mode) : 'rgba(255,255,255,0.2)'}
      <article
        class="lane-row"
        class:stale={lane.stale}
        class:no-data={!lane.hasData}
        style="--lane-color: {laneColor};"
      >
        <div class="weight-bar" style="width: {Math.round((lane.weight || 0) * 100)}%"></div>
        <div class="lane-head">
          <span class="lane-name">{lane.label}</span>
          {#if lane.hasData}
            <span class="lane-mode" style="color: {laneColor}">{lane.mode}</span>
            <span class="lane-conf">{Math.round((lane.confidence || 0) * 100)}%</span>
          {:else}
            <span class="lane-mode muted">—</span>
          {/if}
          {#if lane.agrees && lane.hasData}
            <span class="agree">✓</span>
          {/if}
          {#if lane.stale}
            <span class="stale-tag">STALE</span>
          {/if}
        </div>

        {#if factorsByLane[lane.lane]?.length}
          <div class="factors">
            {#each factorsByLane[lane.lane] as f (f.id)}
              <span class="chip" style="border-color: {modeColorSoft(lane.mode, 0.5)}">
                <span class="chip-key">{f.label}</span>
                <span class="chip-val">{f.display}</span>
              </span>
            {/each}
          </div>
        {/if}
      </article>
    {/each}
  </div>
</section>

<style>
  .mobile {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 16px 12px;
  }

  .nucleus-row {
    display: flex;
    justify-content: center;
    padding: 12px 0 20px;
  }
  .nucleus-disc {
    width: 140px;
    height: 140px;
    border-radius: 50%;
    background: var(--c);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    box-shadow: 0 0 28px var(--halo);
    animation: breathe 4s ease-in-out infinite;
  }
  @keyframes breathe {
    0%, 100% { transform: scale(1);    box-shadow: 0 0 24px var(--halo); }
    50%      { transform: scale(1.03); box-shadow: 0 0 36px var(--halo); }
  }
  .nucleus-label {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 22px;
    letter-spacing: 3px;
    color: rgba(0, 0, 0, 0.85);
  }
  .nucleus-conf {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 14px;
    color: rgba(0, 0, 0, 0.6);
  }

  .lanes {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .lane-row {
    position: relative;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 10px 12px;
    overflow: hidden;
    transition: opacity 0.4s ease;
  }
  .lane-row.stale { opacity: 0.4; }
  .lane-row.no-data { opacity: 0.5; }

  .weight-bar {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    background: var(--lane-color);
    opacity: 0.08;
    pointer-events: none;
    transition: width 500ms ease, background 400ms ease;
  }

  .lane-head {
    display: flex;
    align-items: center;
    gap: 10px;
    position: relative;
    z-index: 1;
  }
  .lane-name {
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 2px;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.7);
    min-width: 72px;
  }
  .lane-mode {
    font-size: 13px;
    font-weight: 500;
    text-transform: capitalize;
  }
  .lane-mode.muted {
    color: rgba(255, 255, 255, 0.3);
  }
  .lane-conf {
    color: rgba(255, 255, 255, 0.4);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }
  .agree {
    color: #30c060;
    font-size: 12px;
  }
  .stale-tag {
    margin-left: auto;
    font-size: 9px;
    font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 1px;
    color: #f0a030;
    background: rgba(240, 160, 48, 0.12);
    padding: 1px 6px;
    border-radius: 4px;
  }

  .factors {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
    position: relative;
    z-index: 1;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 11px;
  }
  .chip-key {
    color: rgba(255, 255, 255, 0.5);
  }
  .chip-val {
    color: rgba(255, 255, 255, 0.85);
  }
</style>
