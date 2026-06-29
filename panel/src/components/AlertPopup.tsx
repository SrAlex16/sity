import { useEffect, useRef } from 'react'

interface Props {
  log: string
  onDismiss: () => void
}

export function AlertPopup({ log, onDismiss }: Props) {
  const logRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.75)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div
        className="alert-modal"
        style={{
          width: 600,
          maxWidth: '90vw',
          background: '#080818',
          border: '2px solid #ff2222',
          borderRadius: 6,
          display: 'flex',
          flexDirection: 'column',
          animation: 'borderPulse 1.5s ease-in-out infinite',
        }}
      >
        {/* Header */}
        <div style={{
          background: '#120808',
          padding: '16px 24px',
          borderBottom: '1px solid #ff222233',
        }}>
          <div style={{
            color: '#ff2222',
            fontSize: '1.1rem',
            fontWeight: 'bold',
            letterSpacing: '0.08em',
            marginBottom: 6,
          }}>
            ⚠ [CRITICAL] SITY BACKEND FAILURE
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.85rem' }}>
            Service <strong style={{ color: '#ff6666' }}>sity-backend</strong> is not responding
          </div>
        </div>

        {/* Body */}
        <div style={{
          padding: '16px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}>
          <div style={{ color: 'var(--text-primary)', fontSize: '0.9rem', lineHeight: 1.6 }}>
            Sity AI assistant is offline.<br />
            Chat, tools and API access are unavailable.<br />
            This monitor continues operating independently.
          </div>

          <div>
            <div style={{
              color: 'var(--text-dim)',
              fontSize: '0.65rem',
              letterSpacing: '0.12em',
              marginBottom: 6,
            }}>
              JOURNAL — últimas 30 líneas
            </div>
            <pre
              ref={logRef}
              style={{
                background: '#030308',
                border: '1px solid #ff222244',
                borderRadius: 3,
                padding: '10px 12px',
                fontSize: '0.75rem',
                color: '#ff6666',
                height: 180,
                overflowY: 'auto',
                fontFamily: 'var(--font-mono)',
                whiteSpace: 'pre',
                lineHeight: 1.5,
              }}
            >
              {log || 'No hay entradas en el journal.'}
            </pre>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 24px',
          display: 'flex',
          justifyContent: 'flex-end',
          borderTop: '1px solid #ff222222',
        }}>
          <button
            onClick={onDismiss}
            style={{
              padding: '8px 24px',
              background: 'transparent',
              border: '1px solid #ff2222',
              borderRadius: 3,
              color: '#ff2222',
              fontSize: '0.8rem',
              letterSpacing: '0.12em',
              fontFamily: 'var(--font-mono)',
              transition: 'background 0.15s, box-shadow 0.15s',
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLButtonElement).style.background = '#ff222222'
              ;(e.currentTarget as HTMLButtonElement).style.boxShadow = '0 0 10px #ff222266'
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
              ;(e.currentTarget as HTMLButtonElement).style.boxShadow = 'none'
            }}
          >
            OK — DISMISS
          </button>
        </div>
      </div>
    </div>
  )
}
