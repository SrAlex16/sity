import type { ProcessInfo } from '../types.d'

// TODO: Cargar icono del proceso desde /usr/share/pixmaps/ o /usr/share/icons/.
// En aarch64 con Electron, las rutas de iconos varían mucho y no hay un estándar
// fiable. Por ahora se muestra la primera letra del nombre en un cuadrado cian.
// Expandir cuando el desktop environment esté definido.

interface Props {
  processes: ProcessInfo[]
}

const SITY_PROCS = new Set(['python3', 'caddy', 'cloudflared'])

function inferType(name: string): string {
  const n = name.toLowerCase()
  if (n.includes('python') || n.includes('node') || n.includes('java')) return 'Runtime'
  if (n.includes('chrome') || n.includes('electron') || n.includes('firefox')) return 'UI'
  if (n.includes('caddy') || n.includes('nginx') || n.includes('apache')) return 'Network'
  if (n.includes('cloud') || n.includes('wpa') || n.includes('net')) return 'Network'
  if (n.includes('systemd') || n.includes('dbus') || n.includes('udev')) return 'System'
  if (n.includes('ssh') || n.includes('sshd')) return 'Network'
  if (n.includes('kernel') || n.includes('kworker') || n.includes('ksoftirqd')) return 'Kernel'
  return 'System'
}

function rowColors(score: number): { bg: string; color: string } {
  if (score < 5)  return { bg: '#050510', color: '#4488aa' }
  if (score < 15) return { bg: '#071428', color: '#00aacc' }
  if (score < 30) return { bg: '#0a1a20', color: '#00ccdd' }
  if (score < 50) return { bg: '#0d2010', color: '#44bb44' }
  if (score < 65) return { bg: '#1a1a08', color: '#aaaa00' }
  if (score < 80) return { bg: '#1a0e00', color: '#cc6600' }
  return           { bg: '#1a0505', color: '#ff2222' }
}

const thStyle: React.CSSProperties = {
  padding: '4px 8px',
  color: 'var(--cyan)',
  fontWeight: 'bold',
  fontSize: 9,
  letterSpacing: '0.12em',
  textAlign: 'left',
  borderBottom: '1px solid var(--border)',
  whiteSpace: 'nowrap',
}

export function ProcessTable({ processes }: Props) {
  return (
    <div style={{
      flex: 1,
      overflow: 'hidden',
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 4,
      display: 'flex',
      flexDirection: 'column',
    }}>
      <table style={{
        width: '100%',
        borderCollapse: 'collapse',
        tableLayout: 'fixed',
      }}>
        <colgroup>
          <col style={{ width: 28 }} />
          <col />
          <col style={{ width: 64 }} />
          <col style={{ width: 64 }} />
          <col style={{ width: 72 }} />
          <col style={{ width: 88 }} />
          <col style={{ width: 72 }} />
        </colgroup>
        <thead>
          <tr>
            <th style={thStyle} />
            <th style={thStyle}>PROCESO</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>PID</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>CPU %</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>RAM MB</th>
            <th style={thStyle}>ESTADO</th>
            <th style={thStyle}>TIPO</th>
          </tr>
        </thead>
      </table>

      <div style={{ overflow: 'auto', flex: 1 }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          tableLayout: 'fixed',
        }}>
          <colgroup>
            <col style={{ width: 28 }} />
            <col />
            <col style={{ width: 64 }} />
            <col style={{ width: 64 }} />
            <col style={{ width: 72 }} />
            <col style={{ width: 88 }} />
            <col style={{ width: 72 }} />
          </colgroup>
          <tbody>
            {processes.map(p => {
              const isSity = SITY_PROCS.has(p.name.toLowerCase())
              // Score = cpu * 0.6 + ram_normalised * 0.4 (ram in MB, normalise to 0–100 assuming max 2000MB)
              const ramScore = Math.min((p.memRss / 2000) * 100, 100)
              const score = p.cpu * 0.6 + ramScore * 0.4
              const { bg, color } = rowColors(score)

              const cellStyle: React.CSSProperties = {
                padding: '3px 8px',
                fontSize: 11,
                color,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                borderBottom: `1px solid ${isSity ? 'var(--magenta)' : '#0e0e1e'}`,
              }

              return (
                <tr
                  key={p.pid}
                  style={{
                    background: bg,
                    outline: isSity ? '1px solid var(--magenta)' : undefined,
                    outlineOffset: '-1px',
                  }}
                >
                  {/* Icon placeholder */}
                  <td style={{ ...cellStyle, padding: '3px 4px' }}>
                    <div style={{
                      width: 16,
                      height: 16,
                      background: isSity ? 'var(--magenta)' : 'var(--cyan)',
                      color: '#000',
                      fontSize: 9,
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
                  <td style={cellStyle} title={p.name}>{p.name}</td>
                  <td style={{ ...cellStyle, textAlign: 'right', color: 'var(--text-dim)' }}>{p.pid}</td>
                  <td style={{ ...cellStyle, textAlign: 'right' }}>{p.cpu.toFixed(1)}</td>
                  <td style={{ ...cellStyle, textAlign: 'right' }}>{p.memRss}</td>
                  <td style={cellStyle}>{p.state}</td>
                  <td style={{ ...cellStyle, color: 'var(--text-dim)' }}>{inferType(p.name)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
