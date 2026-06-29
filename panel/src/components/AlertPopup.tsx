import { useEffect, useRef } from 'react'

interface Props {
  service: string
  log: string
  onDismiss: () => void
}

export function AlertPopup({ service, log, onDismiss }: Props) {
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  return (
    <div className="alert-overlay">
      <div className="alert-modal">
        <div className="alert-head">
          <div className="alert-title">⚠ [CRITICAL] SITY BACKEND FAILURE</div>
          <div className="alert-sub">
            Service <strong style={{ color: '#ff6666' }}>{service}</strong> is not responding
          </div>
        </div>

        <div className="alert-body">
          <div className="alert-desc">
            Sity AI assistant is offline.<br />
            Chat, tools and API access are unavailable.<br />
            This monitor continues operating independently.
          </div>
          <pre className="alert-log" ref={logRef}>
            {log || 'No hay entradas en el journal.'}
          </pre>
        </div>

        <div className="alert-foot">
          <button className="alert-btn" onClick={onDismiss}>
            OK — DISMISS
          </button>
        </div>
      </div>
    </div>
  )
}
