import { memo, useMemo } from 'react'
import { LightCard } from './LightCard'

export const LightGrid = memo(function LightGrid({ lights, onUpdate }) {
  const lightList = useMemo(
    () =>
      Object.values(lights).sort(
        (a, b) => Number(a.light_id) - Number(b.light_id)
      ),
    [lights]
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
})
