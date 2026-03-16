/**
 * RoutineCard — morning routine status and controls.
 */
import { useState, useEffect, memo } from 'react'

export const RoutineCard = memo(function RoutineCard() {
  const [routines, setRoutines] = useState([])
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    fetch('/api/routines')
      .then((r) => r.json())
      .then((data) => setRoutines(data.routines || []))
      .catch(() => {})
  }, [])

  const morningRoutine = routines.find((r) => r.name === 'morning_routine')

  const testMorning = async () => {
    setTesting(true)
    try {
      await fetch('/api/routines/morning/test', { method: 'POST' })
    } catch {
      // ignore
    }
    setTesting(false)
  }

  const toggleMorning = async () => {
    try {
      const resp = await fetch('/api/routines/morning/toggle', { method: 'POST' })
      const data = await resp.json()
      setRoutines((prev) =>
        prev.map((r) =>
          r.name === 'morning_routine' ? { ...r, enabled: data.enabled } : r
        )
      )
    } catch {
      // ignore
    }
  }

  if (!morningRoutine) return null

  return (
    <div className="routine-card">
      <div className="routine-header">
        <div className="routine-info">
          <span className="routine-icon">☀️</span>
          <div>
            <span className="routine-name">Morning Routine</span>
            <span className="routine-time">
              {morningRoutine.time} · Mon–Fri
            </span>
          </div>
        </div>
        <div className="routine-actions">
          <button
            className={`routine-toggle ${morningRoutine.enabled ? 'routine-enabled' : ''}`}
            onClick={toggleMorning}
          >
            {morningRoutine.enabled ? 'ON' : 'OFF'}
          </button>
          <button
            className="routine-test-btn"
            onClick={testMorning}
            disabled={testing}
          >
            {testing ? 'Running...' : 'Test'}
          </button>
        </div>
      </div>
      {morningRoutine.next_run && morningRoutine.enabled && (
        <div className="routine-next">
          Next: {new Date(morningRoutine.next_run).toLocaleString()}
        </div>
      )}
    </div>
  )
})
