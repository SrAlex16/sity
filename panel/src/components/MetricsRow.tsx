import { useEffect, useRef } from 'react'
import type { SystemData, NetworkSample, DiskSample } from '../types.d'

interface Props {
  data: SystemData
}

// ─── Canvas line chart ────────────────────────────────────────────────────────

interface LineChartProps {
  data: number[]
  color: string
  color2?: string
  data2?: number[]
  height?: number
}

function LineChart({ data, color, data2, color2, height = 56 }: LineChartProps) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const c = ref.current
    if (!c) return
    const ctx = c.getContext('2d')
    if (!ctx) return

    const w = c.width
    const h = c.height
    ctx.clearRect(0, 0, w, h)

    function drawSeries(series: number[], clr: string) {
      if (!ctx || series.length < 2) return
      const all = data2 ? [...data, ...data2] : data
      const max = Math.max(...all, 1)
      const step = w / (series.length - 1)

      ctx.beginPath()
      series.forEach((v, i) => {
        const x = i * step
        const y = h - (v / max) * (h - 2) - 1
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
      })
      ctx.strokeStyle = clr
      ctx.lineWidth = 1.5
      ctx.stroke()

      // Fill under line
      ctx.lineTo((series.length - 1) * step, h)
      ctx.lineTo(0, h)
      ctx.closePath()
      ctx.fillStyle = clr + '28'
      ctx.fill()
    }

    drawSeries(data, color)
    if (data2 && color2) drawSeries(data2, color2)
  }, [data, color, data2, color2])

  return (
    <canvas
      ref={ref}
      width={240}
      height={height}
      style={{ width: '100%', height, display: 'block' }}
    />
  )
}

// ─── Single metric card ───────────────────────────────────────────────────────

interface CardProps {
  title: string
  children: React.ReactNode
}

function Card({ title, children }: CardProps) {
  return (
    <div style={{
      flex: 1,
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 4,
      padding: '8px 10px',
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      minWidth: 0,
    }}>
      <div style={{
        color: 'var(--cyan)',
        fontSize: 9,
        letterSpacing: '0.14em',
        fontWeight: 'bold',
        borderBottom: '1px solid var(--border)',
        paddingBottom: 4,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function Stat({ label, value, color = 'var(--text)' }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
      <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>{label}</span>
      <span style={{ color, fontSize: 11, fontWeight: 'bold' }}>{value}</span>
    </div>
  )
}

function pct(n: number) { return `${Math.round(n)}%` }
function gb(n: number)  { return `${n.toFixed(1)} GB` }
function mbps(n: number){ return `${n.toFixed(2)} Mbps` }
function mbs(n: number) { return `${n.toFixed(2)} MB/s` }

// ─── CPU ──────────────────────────────────────────────────────────────────────

function CPUCard({ data }: { data: SystemData }) {
  return (
    <Card title="CPU UTILIZATION">
      <Stat label="Uso" value={pct(data.cpuLoad)} color="var(--cyan)" />
      <Stat label="Núcleos" value={String(data.cpuCores)} />
      <Stat label="Temp" value={data.cpuTemp > 0 ? `${Math.round(data.cpuTemp)}°C` : '--'} />
      <LineChart data={data.cpuHistory} color="var(--cyan)" />
    </Card>
  )
}

// ─── RAM ──────────────────────────────────────────────────────────────────────

function RAMCard({ data }: { data: SystemData }) {
  return (
    <Card title="RAM ALLOCATION">
      <Stat label="Usada" value={gb(data.ramUsed)} color="var(--magenta)" />
      <Stat label="Total" value={gb(data.ramTotal)} />
      <Stat label="%" value={pct(data.ramPercent)} color="var(--magenta)" />
      <div style={{
        height: 12,
        background: 'var(--bg-base)',
        borderRadius: 2,
        overflow: 'hidden',
        border: '1px solid var(--border)',
      }}>
        <div style={{
          height: '100%',
          width: `${Math.min(data.ramPercent, 100)}%`,
          background: 'var(--magenta)',
          transition: 'width 0.4s',
        }} />
      </div>
    </Card>
  )
}

// ─── Network ──────────────────────────────────────────────────────────────────

function NetCard({ data }: { data: SystemData }) {
  const last = data.netHistory[data.netHistory.length - 1]
  const rxH = data.netHistory.map(n => n.rx)
  const txH = data.netHistory.map(n => n.tx)
  return (
    <Card title="NETWORK TRAFFIC">
      <Stat label="DL" value={last ? mbps(last.rx) : '—'} color="var(--cyan)" />
      <Stat label="UL" value={last ? mbps(last.tx) : '—'} color="var(--magenta)" />
      <Stat label="Interfaz" value={data.netInterface} />
      <LineChart data={rxH} color="var(--cyan)" data2={txH} color2="var(--magenta)" />
    </Card>
  )
}

// ─── Disk ─────────────────────────────────────────────────────────────────────

function DiskCard({ data }: { data: SystemData }) {
  const last = data.diskHistory[data.diskHistory.length - 1]
  const rH = data.diskHistory.map(d => d.r)
  const wH = data.diskHistory.map(d => d.w)
  const usedPct = data.diskTotal > 0 ? (data.diskUsed / data.diskTotal) * 100 : 0
  return (
    <Card title="DISK USAGE">
      <Stat label="R" value={last ? mbs(last.r) : '—'} color="var(--cyan)" />
      <Stat label="W" value={last ? mbs(last.w) : '—'} color="var(--magenta)" />
      <Stat label="/" value={data.diskTotal > 0 ? `${gb(data.diskUsed)} / ${gb(data.diskTotal)}` : '—'} />
      {data.diskTotal > 0 && (
        <div style={{
          height: 8,
          background: 'var(--bg-base)',
          borderRadius: 2,
          overflow: 'hidden',
          border: '1px solid var(--border)',
        }}>
          <div style={{
            height: '100%',
            width: `${Math.min(usedPct, 100)}%`,
            background: usedPct > 85 ? 'var(--red)' : usedPct > 70 ? 'var(--yellow)' : 'var(--cyan)',
            transition: 'width 0.4s',
          }} />
        </div>
      )}
      <LineChart data={rH} color="var(--cyan)" data2={wH} color2="var(--magenta)" />
    </Card>
  )
}

// ─── Export ───────────────────────────────────────────────────────────────────

export function MetricsRow({ data }: Props) {
  return (
    <div style={{
      display: 'flex',
      gap: 8,
      flexShrink: 0,
    }}>
      <CPUCard data={data} />
      <RAMCard data={data} />
      <NetCard data={data} />
      <DiskCard data={data} />
    </div>
  )
}
