import { useEffect, useRef } from 'react'
import type { SystemData } from '../types.d'
import { drawLineChart } from '../utils/charts'

interface Props {
  data: SystemData
}

function pct(n: number)  { return `${Math.round(n)}%` }
function gb(n: number)   { return `${n.toFixed(1)} GB` }
function mbps(n: number) { return n < 0.005 ? '—' : `${n.toFixed(2)} Mbps` }
function mbs(n: number)  { return n < 0.001 ? '—' : `${n.toFixed(2)} MB/s` }

export function MetricsRow({ data }: Props) {
  const cpuRef  = useRef<HTMLCanvasElement>(null)
  const ramRef  = useRef<HTMLCanvasElement>(null)
  const netRef  = useRef<HTMLCanvasElement>(null)
  const diskRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (cpuRef.current) drawLineChart(cpuRef.current, data.cpuHistory, '#00f0ff')
  }, [data.cpuHistory])

  useEffect(() => {
    if (ramRef.current) drawLineChart(ramRef.current, data.ramHistory, '#ff00aa')
  }, [data.ramHistory])

  useEffect(() => {
    const paired = data.netHistory.map(n => [n.rx, n.tx] as [number, number])
    if (netRef.current) drawLineChart(netRef.current, paired, '#00f0ff', '#ff00aa')
  }, [data.netHistory])

  useEffect(() => {
    const paired = data.diskHistory.map(d => [d.r, d.w] as [number, number])
    if (diskRef.current) drawLineChart(diskRef.current, paired, '#00f0ff', '#ff00aa')
  }, [data.diskHistory])

  const lastNet  = data.netHistory[data.netHistory.length - 1]
  const lastDisk = data.diskHistory[data.diskHistory.length - 1]
  const usedPct  = data.diskTotal > 0 ? (data.diskUsed / data.diskTotal) * 100 : 0
  const diskFillClass = usedPct > 85 ? 'danger' : 'cyan'
  const tempClass = data.cpuTemp >= 75 ? '#ff2222' : data.cpuTemp >= 60 ? '#aaaa00' : '#00ff88'

  return (
    <div className="metrics">

      {/* CPU */}
      <div className="card">
        <div className="card-title">CPU UTILIZATION</div>
        <div className="card-big cyan">{pct(data.cpuLoad)}</div>
        <div className="card-sub">
          {data.cpuCores} cores ·{' '}
          <span style={{ color: tempClass }}>
            {data.cpuTemp > 0 ? `${Math.round(data.cpuTemp)}°C` : '--'}
          </span>
        </div>
        <div className="graph">
          <canvas ref={cpuRef} />
        </div>
      </div>

      {/* RAM */}
      <div className="card">
        <div className="card-title">RAM ALLOCATION</div>
        <div className="card-big magenta">{gb(data.ramUsed)}</div>
        <div className="card-sub">
          Total <span>{gb(data.ramTotal)}</span> · <span>{pct(data.ramPercent)}</span>
        </div>
        <div className="prog-wrap">
          <div
            className="prog-fill magenta"
            style={{ width: `${Math.min(data.ramPercent, 100)}%` }}
          />
        </div>
        <div className="graph">
          <canvas ref={ramRef} />
        </div>
      </div>

      {/* Network */}
      <div className="card">
        <div className="card-title">NETWORK TRAFFIC</div>
        <div className="net-row">
          <div>
            <div className="net-lbl">DL</div>
            <div className="net-val cyan">{lastNet ? mbps(lastNet.rx) : '—'}</div>
          </div>
          <div>
            <div className="net-lbl">UL</div>
            <div className="net-val magenta">{lastNet ? mbps(lastNet.tx) : '—'}</div>
          </div>
          <div className="card-sub" style={{ alignSelf: 'flex-end' }}>
            {data.netInterface}
          </div>
        </div>
        <div className="graph">
          <canvas ref={netRef} />
        </div>
      </div>

      {/* Disk */}
      <div className="card">
        <div className="card-title">DISK USAGE</div>
        <div className="net-row">
          <div>
            <div className="net-lbl">R</div>
            <div className="net-val cyan">{lastDisk ? mbs(lastDisk.r) : '—'}</div>
          </div>
          <div>
            <div className="net-lbl">W</div>
            <div className="net-val magenta">{lastDisk ? mbs(lastDisk.w) : '—'}</div>
          </div>
        </div>
        {data.diskTotal > 0 && (
          <>
            <div className="card-sub">
              / <span>{gb(data.diskUsed)}</span> / <span>{gb(data.diskTotal)}</span>
            </div>
            <div className="prog-wrap">
              <div
                className={`prog-fill ${diskFillClass}`}
                style={{ width: `${Math.min(usedPct, 100)}%` }}
              />
            </div>
          </>
        )}
        <div className="graph">
          <canvas ref={diskRef} />
        </div>
      </div>

    </div>
  )
}
