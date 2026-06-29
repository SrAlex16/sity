import { useState } from 'react'
import { Header } from './components/Header'
import { MetricsRow } from './components/MetricsRow'
import { ProcessTable } from './components/ProcessTable'
import { ServicesStatus } from './components/ServicesStatus'
import { AlertPopup } from './components/AlertPopup'
import { useSystemData } from './hooks/useSystemData'
import { useServiceStatus } from './hooks/useServiceStatus'

const layout: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  overflow: 'hidden',
  background: 'var(--bg-base)',
}

const body: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
  padding: '0 12px 8px',
  gap: 8,
}

export default function App() {
  const data = useSystemData()
  const { status, log, dismissAlert, alertVisible } = useServiceStatus()
  const [dismissed, setDismissed] = useState(false)

  const showAlert = alertVisible && !dismissed

  function handleDismiss() {
    setDismissed(true)
    dismissAlert()
  }

  // Reset dismissed flag if backend recovers then falls again
  // (dismissAlert() sets alertVisible=false; when it turns true again, dismissed was reset)
  // This is handled inside useServiceStatus via the alertVisible toggle.

  return (
    <div style={layout}>
      <Header uptime={data.uptimeSecs} temp={data.cpuTemp} />

      <div style={body}>
        <ServicesStatus status={status} />
        <MetricsRow data={data} />
        <ProcessTable processes={data.processes} />
      </div>

      {showAlert && (
        <AlertPopup
          log={log}
          onDismiss={handleDismiss}
        />
      )}
    </div>
  )
}
