const SERVICES = ['sity-backend', 'caddy', 'cloudflared']

interface Props {
  services: Record<string, string>
}

export function ServicesStatus({ services }: Props) {
  return (
    <div className="services">
      <span className="svc-label">SERVICIOS</span>
      {SERVICES.map(svc => {
        const s = services[svc]
        const active  = s === 'active'
        const unknown = !s
        const dotCls  = unknown ? 'unk' : active ? 'ok' : 'err'
        const label   = unknown ? '?' : active ? 'ACTIVE' : (s?.toUpperCase() ?? 'INACTIVE')
        return (
          <div key={svc} className="svc">
            <div className={`dot ${dotCls}`} />
            <span className="svc-name">{svc}</span>
            <span className="svc-state">{label}</span>
          </div>
        )
      })}
    </div>
  )
}
