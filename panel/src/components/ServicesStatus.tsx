// TODO: Expandir sistema de alertas con severidades: crítico, grave, medio, leve
// cuando se añadan más servicios monitorizados. Ver issue #XXX para roadmap.

const SERVICES = ['sity-backend', 'caddy', 'cloudflared']

interface Props {
  status: Record<string, string>
}

export function ServicesStatus({ status }: Props) {
  return (
    <div style={{
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      padding: '5px 10px',
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 4,
      flexShrink: 0,
    }}>
      <span style={{ color: 'var(--text-dim)', fontSize: 9, letterSpacing: '0.12em' }}>
        SERVICIOS
      </span>

      {SERVICES.map(svc => {
        const s = status[svc]
        const active = s === 'active'
        const unknown = !s
        return (
          <div key={svc} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{
              fontSize: 14,
              color: unknown ? 'var(--text-dim)' : active ? 'var(--green)' : 'var(--red)',
              lineHeight: 1,
            }}>
              {unknown ? '○' : active ? '●' : '✕'}
            </span>
            <span style={{
              fontSize: 10,
              color: unknown ? 'var(--text-dim)' : active ? 'var(--green)' : 'var(--red)',
              letterSpacing: '0.05em',
            }}>
              {svc}
            </span>
            {!unknown && (
              <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>
                {active ? 'ACTIVE' : s?.toUpperCase() ?? 'INACTIVE'}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}
