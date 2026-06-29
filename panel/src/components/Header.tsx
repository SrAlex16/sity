function fmtUptime(secs: number): string {
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  const m = Math.floor((secs % 3600) / 60)
  return `${d}d ${h}h ${m}m`
}

function tempColor(t: number): string {
  if (t >= 75) return '#ff2222'
  if (t >= 60) return '#aaaa00'
  return '#00ff88'
}

function InfoBlock({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
      <span style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.15em' }}>
        {label}
      </span>
      <span style={{ color, fontSize: '1rem', fontWeight: 'bold', letterSpacing: '0.04em' }}>
        {value}
      </span>
    </div>
  )
}

function WinBtn({ label, onClick, danger }: { label: string; onClick: () => void; danger?: boolean }) {
  const color = danger ? '#ff2222' : 'var(--border-cyan)'
  return (
    <button
      onClick={onClick}
      style={{
        width: 32,
        height: 32,
        background: 'transparent',
        border: `1px solid ${color}`,
        borderRadius: 3,
        color,
        fontSize: '0.85rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLButtonElement).style.boxShadow =
          danger ? '0 0 8px #ff222266' : 'var(--glow-cyan)'
      }}
      onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.boxShadow = 'none' }}
    >
      {label}
    </button>
  )
}

interface HeaderProps {
  uptime: number
  temp: number
}

export function Header({ uptime, temp }: HeaderProps) {
  return (
    <div style={{
      height: 64,
      flexShrink: 0,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      background: 'var(--bg-card)',
      borderBottom: '1px solid var(--border-cyan)',
      boxShadow: '0 2px 20px #00f0ff22',
      WebkitAppRegion: 'drag' as unknown as undefined,
    }}>
      {/* Left: logo + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          background: 'transparent',
          border: '2px solid var(--border-cyan)',
          boxShadow: 'var(--glow-cyan)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--border-cyan)',
          fontWeight: 'bold',
          fontSize: '1.1rem',
          flexShrink: 0,
        }}>
          S
        </div>
        <div>
          <div style={{
            color: 'var(--border-cyan)',
            fontSize: '1.4rem',
            fontWeight: 'bold',
            letterSpacing: '0.15em',
            lineHeight: 1.1,
          }}>
            SITY MONITOR [v1.0]
          </div>
          <div style={{
            color: 'var(--text-dim)',
            fontSize: '0.75rem',
            letterSpacing: '0.1em',
          }}>
            // SYSTEM PROCESSES LIST
          </div>
        </div>
      </div>

      {/* Right: stats + window controls */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 24,
        WebkitAppRegion: 'no-drag' as unknown as undefined,
      }}>
        <InfoBlock label="UPTIME" value={fmtUptime(uptime)} color="var(--border-cyan)" />
        <InfoBlock
          label="TEMP"
          value={temp > 0 ? `${Math.round(temp)}°C` : '--'}
          color={tempColor(temp)}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <WinBtn label="_" onClick={() => window.electronAPI?.minimizeWindow()} />
          <WinBtn label="✕" onClick={() => window.electronAPI?.closeWindow()} danger />
        </div>
      </div>
    </div>
  )
}
