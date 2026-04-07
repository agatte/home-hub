import { useState } from 'react'
import { HubProvider, useConnection, useAutomation, useSonos } from './context/HubContext'
import { Header } from './components/layout/Header'
import { Sidebar } from './components/layout/Sidebar'
import { Home } from './pages/Home'
import { Music } from './pages/Music'
import { Settings } from './pages/Settings'

function AppContent() {
  const { connected, deviceStatus } = useConnection()
  const { automationMode } = useAutomation()
  const { sonos } = useSonos()
  const [page, setPage] = useState('home')

  const renderPage = () => {
    switch (page) {
      case 'music': return <Music />
      case 'settings': return <Settings />
      default: return <Home />
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        page={page}
        onPageChange={setPage}
        mode={automationMode.mode}
        sonos={sonos}
      />
      <div className="app">
        <Header
          connected={connected}
          deviceStatus={deviceStatus}
          page={page}
          onPageChange={setPage}
        />
        {renderPage()}
        {!connected && (
          <div className="reconnect-banner">
            Reconnecting to server...
          </div>
        )}
      </div>
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
