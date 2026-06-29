import { useState, useEffect, useRef } from 'react'

export interface ServiceState {
  status: Record<string, string>
  log: string
  alertVisible: boolean
  dismissAlert: () => void
}

export function useServiceStatus(): ServiceState {
  const [status, setStatus] = useState<Record<string, string>>({})
  const [log, setLog] = useState('')
  const [alertVisible, setAlertVisible] = useState(false)
  // Track previous backend state to detect transitions (active → inactive)
  const prevBackendActive = useRef(true)
  const alertDismissed = useRef(false)

  useEffect(() => {
    const api = window.electronAPI
    if (!api) return

    async function poll() {
      const s = await api.getServiceStatus()
      setStatus(s)

      const backendOk = s['sity-backend'] === 'active'

      if (!backendOk && prevBackendActive.current && !alertDismissed.current) {
        // Backend just went down — fetch log and show alert
        const l = await api.getServiceLog('sity-backend')
        setLog(l)
        setAlertVisible(true)
      }

      if (backendOk) {
        // Backend recovered: reset dismissed flag so next failure shows alert again
        alertDismissed.current = false
      }

      prevBackendActive.current = backendOk
    }

    poll()
    const iv = setInterval(poll, 10_000)
    return () => clearInterval(iv)
  }, [])

  function dismissAlert() {
    setAlertVisible(false)
    alertDismissed.current = true
  }

  return { status, log, alertVisible, dismissAlert }
}
