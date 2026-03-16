import { memo } from 'react'

export const Slider = memo(function Slider({ value, min = 0, max = 100, onChange, label, className = '' }) {
  return (
    <div className={`slider-container ${className}`}>
      {label && <label className="slider-label">{label}</label>}
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="slider-input"
      />
      <span className="slider-value">{value}</span>
    </div>
  )
})
