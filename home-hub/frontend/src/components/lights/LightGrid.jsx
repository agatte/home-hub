import { LightCard } from './LightCard'

export function LightGrid({ lights, onUpdate }) {
  const lightList = Object.values(lights).sort(
    (a, b) => Number(a.light_id) - Number(b.light_id)
  )

  if (lightList.length === 0) {
    return <div className="empty-state">No lights found</div>
  }

  return (
    <div className="light-grid">
      {lightList.map((light) => (
        <LightCard key={light.light_id} light={light} onUpdate={onUpdate} />
      ))}
    </div>
  )
}
