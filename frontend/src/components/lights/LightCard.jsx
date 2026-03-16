import { memo, useCallback, useRef } from 'react'
import { Slider } from '../common/Slider'

const COLOR_PRESETS = [
  { name: 'Warm', hue: 8000, sat: 140 },
  { name: 'Cool', hue: 34000, sat: 50 },
  { name: 'Daylight', hue: 41000, sat: 30 },
  { name: 'Blue', hue: 46920, sat: 254 },
  { name: 'Red', hue: 0, sat: 254 },
  { name: 'Green', hue: 25500, sat: 254 },
  { name: 'Purple', hue: 50000, sat: 254 },
]

function hueToHsl(hue, sat, bri) {
  const h = (hue / 65535) * 360
  const s = (sat / 254) * 100
  const l = (bri / 254) * 50
  return `hsl(${h}, ${s}%, ${Math.max(l, 20)}%)`
}

export const LightCard = memo(function LightCard({ light, onUpdate }) {
  const debounceRef = useRef(null)

  const debouncedUpdate = useCallback(
    (state) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        onUpdate(light.light_id, state)
      }, 100)
    },
    [light.light_id, onUpdate]
  )

  const togglePower = () => {
    onUpdate(light.light_id, { on: !light.on })
  }

  const setBrightness = (bri) => {
    debouncedUpdate({ bri })
  }

  const setColor = (hue, sat) => {
    onUpdate(light.light_id, { hue, sat })
  }

  const bgColor = light.on
    ? hueToHsl(light.hue, light.sat, light.bri)
    : '#1a1a2e'

  return (
    <div className={`light-card ${light.on ? 'light-on' : 'light-off'}`}>
      <div className="light-header">
        <div className="light-indicator" style={{ background: light.on ? bgColor : '#333' }} />
        <span className="light-name">{light.name}</span>
        <button
          className={`power-btn ${light.on ? 'power-on' : ''}`}
          onClick={togglePower}
          aria-label={light.on ? 'Turn off' : 'Turn on'}
        >
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2v6M18.36 6.64A9 9 0 1 1 5.64 6.64" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {light.on && (
        <>
          <Slider
            value={light.bri}
            min={1}
            max={254}
            onChange={setBrightness}
            label="Brightness"
          />
          <div className="color-presets">
            {COLOR_PRESETS.map((preset) => (
              <button
                key={preset.name}
                className={`color-preset ${
                  Math.abs(light.hue - preset.hue) < 2000 &&
                  Math.abs(light.sat - preset.sat) < 50
                    ? 'color-active'
                    : ''
                }`}
                style={{ background: hueToHsl(preset.hue, preset.sat, 200) }}
                onClick={() => setColor(preset.hue, preset.sat)}
                title={preset.name}
              />
            ))}
          </div>
        </>
      )}

      {!light.reachable && <div className="light-unreachable">Unreachable</div>}
    </div>
  )
})
