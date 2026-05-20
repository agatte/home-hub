<script>
  import Slider from '$lib/components/Slider.svelte'

  /** @typedef {{key: string, label: string}} Period */

  /** @type {Period[]} */
  export let periods = [
    { key: 'day', label: 'Day' },
    { key: 'evening', label: 'Evening' },
    { key: 'night', label: 'Night' },
  ]
  /** @type {Record<string, number>} */
  export let values = {}
  export let min = 0
  export let max = 60
  export let liveUpdate = false
  /** @type {(key: string, value: number) => void} */
  export let onChange = () => {}
</script>

<div class="period-sliders">
  {#each periods as period (period.key)}
    <div class="period-cell">
      <div class="period-head">
        <span class="period-label">{period.label}</span>
        <span class="period-value">{values[period.key] ?? 0}</span>
      </div>
      <Slider
        value={values[period.key] ?? 0}
        {min}
        {max}
        {liveUpdate}
        onChange={(v) => onChange(period.key, v)}
      />
    </div>
  {/each}
</div>

<style>
  .period-sliders {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px;
  }

  .period-cell {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .period-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 6px;
  }

  .period-label {
    font-family: var(--font-body);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
  }

  .period-value {
    font-family: var(--font-body);
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }

  @media (max-width: 540px) {
    .period-sliders {
      grid-template-columns: 1fr;
      gap: 10px;
    }
  }
</style>
