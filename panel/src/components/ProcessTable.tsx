import type { ProcessInfo } from '../types.d'

interface Props {
  processes: ProcessInfo[]
  totalRamKb: number  // total RAM in same unit as proc.memRss (MB) for % calc
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

function tierClass(score: number): string {
  if (score > 80) return 't6'
  if (score > 60) return 't5'
  if (score > 40) return 't4'
  if (score > 20) return 't3'
  if (score > 8)  return 't2'
  if (score > 2)  return 't1'
  return 't0'
}

function stateClass(state: string): string {
  const s = state.toLowerCase()
  if (s === 'running' || s === 'r') return 'state-run'
  if (s === 'sleeping' || s === 's') return 'state-slp'
  if (s === 'zombie'  || s === 'z') return 'state-zzz'
  return 'state-unk'
}

export function ProcessTable({ processes, totalRamKb }: Props) {
  return (
    <div className="proc-section">
      <div className="proc-header-bar">
        <span>ACTIVE PROCESSES</span>
        <span className="proc-count">[{processes.length}] // SYSTEM THREAD LIST</span>
      </div>

      <div className="table-wrap">
        <table>
          <colgroup>
            <col style={{ width: 40 }} />
            <col />
            <col style={{ width: 76 }} />
            <col style={{ width: 76 }} />
            <col style={{ width: 86 }} />
            <col style={{ width: 96 }} />
            <col style={{ width: 86 }} />
          </colgroup>
          <thead>
            <tr>
              <th />
              <th>PROCESO</th>
              <th className="r">PID</th>
              <th className="r">CPU %</th>
              <th className="r">RAM MB</th>
              <th>ESTADO</th>
              <th>TIPO</th>
            </tr>
          </thead>
          <tbody>
            {processes.map(proc => {
              const isSity  = SITY_PROCS.has(proc.name.toLowerCase())
              const ramPct  = totalRamKb > 0 ? (proc.memRss / totalRamKb) * 100 : 0
              const score   = proc.cpu * 0.7 + ramPct * 0.3
              const rowCls  = `${tierClass(score)}${isSity ? ' sity-row' : ''}`
              const stateCls = stateClass(proc.state)

              return (
                <tr key={proc.pid} className={rowCls}>
                  <td>
                    <div className="icon-box">
                      {proc.name[0]?.toUpperCase() ?? '?'}
                    </div>
                  </td>
                  <td title={proc.name}>
                    <span className="proc-name">{proc.name}</span>
                  </td>
                  <td className="r">
                    <span className="pid-val">{proc.pid}</span>
                  </td>
                  <td className="r">{proc.cpu.toFixed(1)}</td>
                  <td className="r">{proc.memRss > 0 ? proc.memRss : '—'}</td>
                  <td>
                    <span className={stateCls}>{proc.state}</span>
                  </td>
                  <td>
                    <span className="type-lbl">{inferType(proc.name)}</span>
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
