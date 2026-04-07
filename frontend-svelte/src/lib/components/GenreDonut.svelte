<script>
  /** @type {Record<string, number> | null | undefined} */
  export let distribution = null

  const GENRE_COLORS = [
    '#4a6cf7', '#f472b6', '#34d399', '#fbbf24', '#a78bfa',
    '#f87171', '#38bdf8', '#fb923c', '#818cf8', '#2dd4bf',
    '#e879f9', '#facc15',
  ]

  $: segments = (() => {
    if (!distribution || Object.keys(distribution).length === 0) return []

    /** @type {Array<[string, number]>} */
    const entries = Object.entries(distribution)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)

    const topWeight = entries.reduce((sum, [, w]) => sum + w, 0)
    const otherWeight = 1 - topWeight
    if (otherWeight > 0.01) entries.push(['other', otherWeight])

    let offset = 0
    return entries.map(([genre, weight], i) => {
      const seg = {
        genre,
        weight,
        percent: Math.round(weight * 100),
        color: GENRE_COLORS[i % GENRE_COLORS.length],
        offset,
      }
      offset += weight
      return seg
    })
  })()

  $: gradientStops = segments
    .map((seg) => {
      const start = (seg.offset * 360).toFixed(1)
      const end = ((seg.offset + seg.weight) * 360).toFixed(1)
      return `${seg.color} ${start}deg ${end}deg`
    })
    .join(', ')
</script>

{#if segments.length > 0}
  <div class="genre-donut-container">
    <div class="genre-donut" style="background: conic-gradient({gradientStops})">
      <div class="genre-donut-hole"></div>
    </div>
    <div class="genre-legend">
      {#each segments.filter((s) => s.percent >= 2) as seg (seg.genre)}
        <div class="genre-legend-item">
          <span class="genre-legend-dot" style="background: {seg.color}"></span>
          <span class="genre-legend-label">{seg.genre}</span>
          <span class="genre-legend-value">{seg.percent}%</span>
        </div>
      {/each}
    </div>
  </div>
{/if}
