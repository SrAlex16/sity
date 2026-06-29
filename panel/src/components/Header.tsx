function fmtUptime(secs: number): string {
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  const m = Math.floor((secs % 3600) / 60)
  return `${d}d ${h}h ${m}m`
}

interface Props {
  uptime: number
  temp: number
  onMinimize: () => void
  onClose: () => void
}

export function Header({ uptime, temp, onMinimize, onClose }: Props) {
  const tempClass = temp >= 75 ? 'hot' : temp >= 60 ? 'warn' : ''
  return (
    <header
      className="header"
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
    >
      <div className="header-left">
        <div className="logo">S</div>
        <div>
          <div className="header-title">SITY MONITOR [v1.0]</div>
          <div className="header-sub">// SYSTEM PROCESSES LIST</div>
        </div>
      </div>

      <div
        className="header-right"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
      >
        <div className="stat-block">
          <div className="stat-label">UPTIME</div>
          <div className="stat-value">{fmtUptime(uptime)}</div>
        </div>
        <div className="stat-block">
          <div className="stat-label">TEMP</div>
          <div className={`stat-value${tempClass ? ' ' + tempClass : ''}`}>
            {temp > 0 ? `${Math.round(temp)}°C` : '--'}
          </div>
        </div>
        <div className="win-buttons">
          <button className="win-btn" onClick={onMinimize}>_</button>
          <button className="win-btn close" onClick={onClose}>✕</button>
        </div>
      </div>
    </header>
  )
}
