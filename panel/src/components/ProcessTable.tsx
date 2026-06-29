import type { ProcessInfo } from '../types.d'

interface Props {
  processes: ProcessInfo[]
  ramTotal: number  // GB — for score calculation
}

const SITY_PROCS = new Set(['python3', 'caddy', 'cloudflared'])

function inferType(name: string): string {
  const n = name.toLowerCase()
  if (n.includes('python') || n.includes('node') || n.includes('java')) return 'Runtime'
  if (n.includes('chrome') || n.includes('electron') || n.includes('firefox')) return 'UI'
  if (n.includes('caddy') || n.includes('nginx') || n.includes('apache')) return 'Network'
  if (n.includes('cloud') || n.includes('wpa') || n.includes('net')) return 'Network'
  if (n.includes('ssh')) return 'Network'
  if (n.includes('kernel') || n.includes('kworker') || n.includes('ksoftirqd')) return 'Kernel'
  return 'System'
}

function rowColors(score: number): { bg: string; color: string } {
  if (score < 2)  return { bg: '#050510', color: '#2a5566' }
  if (score < 8)  return { bg: '#060a18', color: '#00aacc' }
  if (score < 20) return { bg: '#071520', color: '#00ccdd' }
  if (score < 40) return { bg: '#081f10', color: '#44bb44' }
  if (score < 60) return { bg: '#181808', color: '#cccc00' }
  if (score < 80) return { bg: '#1a0e00', color: '#cc6600' }
  return           { bg: '#180505', color: '#ff3333' }
}

function stateColor(state: string): string {
  const s = state.toLowerCase()
  if (s === 'running' || s === 'r') return '#00ff88'
  if (s === 'zombie'  || s === 'z') return '#ff2222'
  return 'var(--text-dim)'
}

const colgroup = (
  <colgroup>
    <col style={{ width: 44 }} />
    <col />
    <col style={{ width: 76 }} />
    <col style={{ width: 76 }} />
    <col style={{ width: 86 }} />
    <col style={{ width: 96 }} />
    <col style={{ width: 86 }} />
  </colgroup>
)

const thBase: React.CSSProperties = {
  padding: '0 8px',
  color: 'var(--border-cyan)',
  fontSize: '0.72rem',
  letterSpacing: '0.12em',
  fontWeight: 'bold',
  textAlign: 'left',
  height: 32,
  borderBottom: '1px solid var(--border-cyan)',
  background: '#0a0a20',
  whiteSpace: 'nowrap',
}

export function ProcessTable({ processes, ramTotal }: Props) {
  const ramTotalMB = ramTotal * 1024

  return (
    <div style={{
      flex: 1,
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--bg-card)',
      border: '1px solid var(--border-cyan)',
      borderRadius: 4,
      boxShadow: '0 0 12px #00f0ff22',
    }}>
      {/* Section label */}
      <div style={{
        padding: '5px 14px',
        background: '#08081a',
        borderBottom: '1px solid #00f0ff30',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
      }}>
        <span style={{ color: 'var(--border-cyan)', fontSize: '0.7rem', letterSpacing: '0.18em', fontWeight: 'bold' }}>
          ACTIVE PROCESSES
        </span>
        <span style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.1em' }}>
          [{processes.length}] // SYSTEM THREAD LIST
        </span>
      </div>

      {/* Sticky header */}
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed', flexShrink: 0 }}>
        {colgroup}
        <thead>
          <tr>
            <th style={thBase} />
            <th style={thBase}>PROCESO</th>
            <th style={{ ...thBase, textAlign: 'right' }}>PID</th>
            <th style={{ ...thBase, textAlign: 'right' }}>CPU %</th>
            <th style={{ ...thBase, textAlign: 'right' }}>RAM MB</th>
            <th style={thBase}>ESTADO</th>
            <th style={thBase}>TIPO</th>
          </tr>
        </thead>
      </table>

      {/* Scrollable body */}
      <div style={{ overflow: 'auto', flex: 1 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
          {colgroup}
          <tbody>
            {processes.map(p => {
              const isSity   = SITY_PROCS.has(p.name.toLowerCase())
              const ramPct   = ramTotalMB > 0 ? Math.min((p.memRss / ramTotalMB) * 100, 100) : 0
              const score    = p.cpu * 0.7 + ramPct * 0.3
              const { bg, color } = rowColors(score)
              const sityBorder = isSity ? '3px solid var(--border-magenta)' : undefined

              const cell: React.CSSProperties = {
                padding: '0 8px',
                height: 36,
                fontSize: '0.88rem',
                color,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                borderBottom: '1px solid #0d0d20',
                borderLeft: sityBorder,
              }

              return (
                <tr
                  key={p.pid}
                  style={{
                    background: isSity ? bg + 'cc' : bg,
                    outline: isSity ? '1px solid #ff00aa44' : undefined,
                    outlineOffset: '-1px',
                  }}
                >
                  {/* Icon */}
                  <td style={{ ...cell, padding: '0 6px', borderLeft: sityBorder }}>
                    <div style={{
                      width: 26,
                      height: 26,
                      background: 'transparent',
                      border: `1px solid ${isSity ? 'var(--border-magenta)' : 'var(--border-cyan)'}`,
                      color: isSity ? 'var(--border-magenta)' : 'var(--border-cyan)',
                      fontSize: '0.7rem',
                      fontWeight: 'bold',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: 2,
                      flexShrink: 0,
                    }}>
                      {p.name[0]?.toUpperCase() ?? '?'}
                    </div>
                  </td>
                  <td style={cell} title={p.name}>{p.name}</td>
                  <td style={{ ...cell, textAlign: 'right', color: 'var(--text-dim)', fontSize: '0.78rem', borderLeft: undefined }}>
                    {p.pid}
                  </td>
                  <td style={{ ...cell, textAlign: 'right', borderLeft: undefined }}>
                    {p.cpu.toFixed(1)}
                  </td>
                  <td style={{ ...cell, textAlign: 'right', borderLeft: undefined }}>
                    {p.memRss > 0 ? p.memRss : '—'}
                  </td>
                  <td style={{ ...cell, color: stateColor(p.state), borderLeft: undefined }}>
                    {p.state}
                  </td>
                  <td style={{ ...cell, color: 'var(--text-dim)', borderLeft: undefined }}>
                    {inferType(p.name)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
