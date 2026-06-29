const SERVICES = ['sity-backend', 'caddy', 'cloudflared']

interface Props {
  status: Record<string, string>
}

export function ServicesStatus({ status }: Props) {
  return (
    <div style={{
      height: 32,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      gap: '2rem',
      padding: '0 14px',
      background: '#060614',
      borderBottom: '1px solid #00f0ff40',
    }}>
      <span style={{
        color: 'var(--text-dim)',
        fontSize: '0.65rem',
        letterSpacing: '0.18em',
        marginRight: 4,
      }}>
        SERVICIOS
      </span>

      {SERVICES.map(svc => {
        const s = status[svc]
        const active  = s === 'active'
        const unknown = !s
        const dotColor = unknown ? 'var(--text-dim)' : active ? '#00ff88' : '#ff2222'
        const stateLabel = unknown ? '?' : active ? 'ACTIVE' : (s?.toUpperCase() ?? 'INACTIVE')

        return (
          <div key={svc} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: '0.85rem', color: dotColor, lineHeight: 1 }}>●</span>
            <span style={{
              color: 'var(--border-cyan)',
              fontSize: '0.78rem',
              letterSpacing: '0.04em',
            }}>
              {svc}
            </span>
            <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem' }}>
              {stateLabel}
            </span>
          </div>
        )
      })}
    </div>
  )
}
