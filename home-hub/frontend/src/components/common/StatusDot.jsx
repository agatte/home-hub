export function StatusDot({ active, label }) {
  return (
    <div className="status-dot-container">
      <span
        className={`status-dot ${active ? 'status-active' : 'status-inactive'}`}
      />
      {label && <span className="status-label">{label}</span>}
    </div>
  )
}
