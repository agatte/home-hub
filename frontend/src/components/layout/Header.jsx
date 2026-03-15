import { StatusDot } from '../common/StatusDot'

export function Header({ connected, deviceStatus }) {
  return (
    <header className="app-header">
      <h1 className="app-title">Home Hub</h1>
      <div className="status-bar">
        <StatusDot active={connected} label="Server" />
        <StatusDot active={deviceStatus.hue} label="Hue" />
        <StatusDot active={deviceStatus.sonos} label="Sonos" />
      </div>
    </header>
  )
}
