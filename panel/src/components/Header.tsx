import React from 'react'

interface HeaderProps {
  uptime: number
  temp: number
}

function fmtUptime(secs: number): string {
  const d = Math.floor(secs / 86400)
  const h = Math.floor((secs % 86400) / 3600)
  const m = Math.floor((secs % 3600) / 60)
  return `${d}d ${h}h ${m}m`
}

function tempColor(t: number): string {
  if (t >= 75) return 'var(--red)'
  if (t >= 60) return 'var(--yellow)'
  return 'var(--green)'
}

const wrap: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '6px 12px',
  background: 'var(--bg-surface)',
  borderBottom: '1px solid var(--border)',
  position: 'relative',
  WebkitAppRegion: 'drag' as unknown as undefined,
}

const logo: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 10,
}

const circle: React.CSSProperties = {
  width: 28,
  height: 28,
  borderRadius: '50%',
  background: 'var(--cyan)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#000',
  fontWeight: 'bold',
  fontSize: 14,
  flexShrink: 0,
}

const title: React.CSSProperties = {
  color: 'var(--cyan)',
  fontSize: 13,
  letterSpacing: '0.12em',
  fontWeight: 'bold',
}

const sub: React.CSSProperties = {
  color: 'var(--text-dim)',
  fontSize: 10,
  letterSpacing: '0.1em',
}

const right: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 20,
}

const infoBlock: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'flex-end',
  gap: 2,
}

const label: React.CSSProperties = {
  color: 'var(--text-dim)',
  fontSize: 9,
  letterSpacing: '0.1em',
}

const controls: React.CSSProperties = {
  display: 'flex',
  gap: 6,
  WebkitAppRegion: 'no-drag' as unknown as undefined,
}

const btnStyle = (color: string): React.CSSProperties => ({
  width: 18,
  height: 18,
  background: 'transparent',
  border: `1px solid ${color}`,
  borderRadius: 2,
  color,
  fontSize: 10,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  cursor: 'pointer',
  lineHeight: 1,
})

export function Header({ uptime, temp }: HeaderProps) {
  return (
    <div style={wrap}>
      <div style={logo}>
        <div style={circle}>S</div>
        <div>
          <div style={title}>SITY MONITOR [v1.0]</div>
          <div style={sub}>// SYSTEM PROCESSES LIST</div>
        </div>
      </div>

      <div style={right}>
        <div style={infoBlock}>
          <span style={label}>UPTIME</span>
          <span style={{ color: 'var(--cyan)', fontSize: 11 }}>{fmtUptime(uptime)}</span>
        </div>
        <div style={infoBlock}>
          <span style={label}>TEMP</span>
          <span style={{ color: tempColor(temp), fontSize: 11 }}>
            {temp > 0 ? `${Math.round(temp)}°C` : '--'}
          </span>
        </div>
        <div style={controls}>
          <button
            style={btnStyle('var(--text-dim)')}
            onClick={() => window.electronAPI?.minimizeWindow()}
            title="Minimizar"
          >
            _
          </button>
          <button
            style={btnStyle('var(--red)')}
            onClick={() => window.electronAPI?.closeWindow()}
            title="Cerrar"
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  )
}
