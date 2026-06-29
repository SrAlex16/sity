import { useEffect, useRef, useState } from 'react'

interface Props {
  log: string
  onDismiss: () => void
}

export function AlertPopup({ log, onDismiss }: Props) {
  const logRef = useRef<HTMLPreElement>(null)
  const [blink, setBlink] = useState(true)

  // Scroll log to bottom on open
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [log])

  // Border blink animation via JS (no keyframes needed)
  useEffect(() => {
    const iv = setInterval(() => setBlink(b => !b), 600)
    return () => clearInterval(iv)
  }, [])

  const borderColor = blink ? 'var(--magenta)' : 'var(--red)'

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: 'var(--bg-card)',
        border: `2px solid ${borderColor}`,
        borderRadius: 6,
        padding: '20px 24px',
        width: 600,
        maxWidth: '90vw',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        boxShadow: `0 0 32px ${borderColor}44`,
        transition: 'border-color 0.1s, box-shadow 0.1s',
      }}>
        <div style={{ color: 'var(--red)', fontSize: 14, fontWeight: 'bold', letterSpacing: '0.1em' }}>
          ⚠ [CRITICAL] SITY BACKEND FAILURE
        </div>

        <div style={{ color: 'var(--magenta)', fontSize: 11 }}>
          Service <strong>sity-backend</strong> is not responding
        </div>

        <div style={{ color: 'var(--text)', fontSize: 11, lineHeight: 1.6 }}>
          Sity AI assistant is offline. Chat, tools and API access are unavailable.
          The monitor continues operating independently.
        </div>

        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 9, letterSpacing: '0.1em', marginBottom: 4 }}>
            JOURNAL — últimas 30 líneas
          </div>
          <pre
            ref={logRef}
            style={{
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              borderRadius: 3,
              padding: '8px 10px',
              fontSize: 10,
              color: 'var(--text-dim)',
              maxHeight: 200,
              overflowY: 'auto',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {log || 'No hay entradas en el journal.'}
          </pre>
        </div>

        <button
          onClick={onDismiss}
          style={{
            alignSelf: 'flex-end',
            padding: '6px 20px',
            background: 'transparent',
            border: '1px solid var(--magenta)',
            borderRadius: 3,
            color: 'var(--magenta)',
            fontSize: 11,
            letterSpacing: '0.1em',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
          }}
        >
          OK — DISMISS
        </button>
      </div>
    </div>
  )
}
