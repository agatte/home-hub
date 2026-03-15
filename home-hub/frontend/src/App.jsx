import { HubProvider, useHub } from './context/HubContext'
import { Header } from './components/layout/Header'
import { Home } from './pages/Home'

function AppContent() {
  const { connected, deviceStatus } = useHub()

  return (
    <div className="app">
      <Header connected={connected} deviceStatus={deviceStatus} />
      <Home />
      {!connected && (
        <div className="reconnect-banner">
          Reconnecting to server...
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <HubProvider>
      <AppContent />
    </HubProvider>
  )
}
