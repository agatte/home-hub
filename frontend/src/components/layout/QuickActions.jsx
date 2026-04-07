import { memo, useCallback } from 'react'

/**
 * Quick action strip — top-of-Home one-tap shortcuts.
 *
 * Buttons highlight when their target mode matches the current mode.
 * "All off" hits the lights/all endpoint directly; everything else
 * goes through setManualMode.
 */
export const QuickActions = memo(function QuickActions({ currentMode, onMode }) {
  const allOff = useCallback(async () => {
    try {
      await fetch('/api/lights/all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ on: false }),
      })
    } catch {
      /* ignore */
    }
  }, [])

  const actions = [
    { id: 'movie', label: 'Movie', mode: 'movie' },
    { id: 'relax', label: 'Relax', mode: 'relax' },
    { id: 'social', label: 'Party', mode: 'social' },
    { id: 'sleeping', label: 'Bedtime', mode: 'sleeping' },
    { id: 'auto', label: 'Auto', mode: 'auto' },
  ]

  return (
    <div className="quick-actions">
      <button className="quick-action quick-action-danger" onClick={allOff}>
        All off
      </button>
      {actions.map((a) => (
        <button
          key={a.id}
          className={`quick-action ${currentMode === a.mode ? 'quick-action-active' : ''}`}
          onClick={() => onMode(a.mode)}
        >
          {a.label}
        </button>
      ))}
    </div>
  )
})
