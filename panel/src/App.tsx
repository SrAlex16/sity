import { Header } from './components/Header'
import { MetricsRow } from './components/MetricsRow'
import { ProcessTable } from './components/ProcessTable'
import { ServicesStatus } from './components/ServicesStatus'
import { AlertPopup } from './components/AlertPopup'
import { useSystemData } from './hooks/useSystemData'
import { useServiceStatus } from './hooks/useServiceStatus'

export default function App() {
  const data = useSystemData()
  const { status, log, dismissAlert, alertVisible } = useServiceStatus()

  const showAlert = alertVisible

  return (
    <div className="layout">
      <Header
        uptime={data.uptimeSecs}
        temp={data.cpuTemp}
        onMinimize={() => window.electronAPI?.minimizeWindow()}
        onClose={() => window.electronAPI?.closeWindow()}
      />
      <ServicesStatus services={status} />
      <MetricsRow data={data} />
      <ProcessTable
        processes={data.processes}
        totalRamKb={data.ramTotal * 1024}
      />
      {showAlert && (
        <AlertPopup
          service="sity-backend"
          log={log}
          onDismiss={dismissAlert}
        />
      )}
    </div>
  )
}
