import { useState } from 'react'
import { HubProvider, useConnection } from './context/HubContext'
import { Header } from './components/layout/Header'
import { Home } from './pages/Home'
import { Music } from './pages/Music'
import { Settings } from './pages/Settings'

function AppContent() {
  const { connected, deviceStatus } = useConnection()
  const [page, setPage] = useState('home')

  const renderPage = () => {
    switch (page) {
      case 'music': return <Music />
      case 'settings': return <Settings />
      default: return <Home />
    }
  }

  return (
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
  )
}

export default function App() {
  return (
    <HubProvider>
      <AppContent />
    </HubProvider>
  )
}
