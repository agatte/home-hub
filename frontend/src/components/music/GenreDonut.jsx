import { memo, useMemo } from 'react'

const GENRE_COLORS = [
  '#4a6cf7', '#f472b6', '#34d399', '#fbbf24', '#a78bfa',
  '#f87171', '#38bdf8', '#fb923c', '#818cf8', '#2dd4bf',
  '#e879f9', '#facc15',
]

export const GenreDonut = memo(function GenreDonut({ distribution }) {
  const segments = useMemo(() => {
    if (!distribution || Object.keys(distribution).length === 0) return []

    const entries = Object.entries(distribution)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)

    // Group remaining into "Other"
    const topWeight = entries.reduce((sum, [, w]) => sum + w, 0)
    const otherWeight = 1 - topWeight
    if (otherWeight > 0.01) {
      entries.push(['other', otherWeight])
    }

    let offset = 0
    return entries.map(([genre, weight], i) => {
      const segment = {
        genre,
        weight,
        percent: Math.round(weight * 100),
        color: GENRE_COLORS[i % GENRE_COLORS.length],
        offset,
      }
      offset += weight
      return segment
    })
  }, [distribution])

  if (segments.length === 0) return null

  // Build conic-gradient
  const gradientStops = segments.map((seg) => {
    const start = (seg.offset * 360).toFixed(1)
    const end = ((seg.offset + seg.weight) * 360).toFixed(1)
    return `${seg.color} ${start}deg ${end}deg`
  }).join(', ')

  return (
    <div className="genre-donut-container">
      <div
        className="genre-donut"
        style={{ background: `conic-gradient(${gradientStops})` }}
      >
        <div className="genre-donut-hole" />
      </div>
      <div className="genre-legend">
        {segments.filter(s => s.percent >= 2).map((seg) => (
          <div key={seg.genre} className="genre-legend-item">
            <span
              className="genre-legend-dot"
              style={{ background: seg.color }}
            />
            <span className="genre-legend-label">
              {seg.genre}
            </span>
            <span className="genre-legend-value">{seg.percent}%</span>
          </div>
        ))}
      </div>
    </div>
  )
})
