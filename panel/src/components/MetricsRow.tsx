import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { SystemData } from '../types.d'

interface Props {
  data: SystemData
}

// ─── Canvas line chart ────────────────────────────────────────────────────────

function LineChart({ data, color, data2, color2, height = 60 }: {
  data: number[]
  color: string
  data2?: number[]
  color2?: string
  height?: number
}) {
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
      const all = data2 ? [...data, ...(data2 ?? [])] : data
      const max = Math.max(...all, 1)
      const step = w / (series.length - 1)
      ctx.beginPath()
      series.forEach((v, i) => {
        const x = i * step
        const y = h - (v / max) * (h - 2) - 1
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
      })
      ctx.strokeStyle = clr
      ctx.lineWidth = 2
      ctx.stroke()
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
      width={280}
      height={height}
      style={{ width: '100%', height, display: 'block' }}
    />
  )
}

// ─── Vertical bar chart ───────────────────────────────────────────────────────

function BarChart({ data, color, height = 40 }: {
  data: number[]
  color: string
  height?: number
}) {
  const bars = data.slice(-30)
  const max  = Math.max(...bars, 1)
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height }}>
      {bars.map((v, i) => (
        <div
          key={i}
          style={{
            flex: 1,
            height: `${Math.max((v / max) * 100, 2)}%`,
            background: color,
            minWidth: 2,
            borderRadius: 1,
            opacity: 0.7 + (i / bars.length) * 0.3,
          }}
        />
      ))}
    </div>
  )
}

// ─── Card wrapper ─────────────────────────────────────────────────────────────

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      className="card-corners"
      style={{
        flex: 1,
        height: 200,
        background: 'var(--bg-card)',
        border: '1px solid var(--border-cyan)',
        borderRadius: 4,
        padding: '10px 12px',
        display: 'flex',
        flexDirection: 'column',
        gap: 5,
        minWidth: 0,
        boxShadow: '0 0 12px #00f0ff22',
      }}
    >
      <div style={{
        color: 'var(--border-cyan)',
        fontSize: '0.7rem',
        letterSpacing: '0.2em',
        fontWeight: 'bold',
        borderBottom: '1px solid #00f0ff30',
        paddingBottom: 5,
        marginBottom: 2,
        flexShrink: 0,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function BigVal({ value, color }: { value: string; color: string }) {
  return (
    <div style={{
      fontSize: '2.8rem',
      fontWeight: 'bold',
      color,
      lineHeight: 1,
      letterSpacing: '-0.02em',
      flexShrink: 0,
    }}>
      {value}
    </div>
  )
}

function Row({ label, value, color = 'var(--text-dim)' }: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      flexShrink: 0,
    }}>
      <span style={{ color: 'var(--text-dim)', fontSize: '0.78rem' }}>{label}</span>
      <span style={{ color, fontSize: '0.78rem', fontWeight: 'bold' }}>{value}</span>
    </div>
  )
}

function MedVal({ value, color }: { value: string; color: string }) {
  return (
    <div style={{
      fontSize: '1.35rem',
      fontWeight: 'bold',
      color,
      lineHeight: 1.2,
      letterSpacing: '-0.01em',
      flexShrink: 0,
    }}>
      {value}
    </div>
  )
}

function pct(n: number) { return `${Math.round(n)}%` }
function gb(n: number)  { return `${n.toFixed(1)} GB` }
function mbps(n: number){ return n < 0.01 ? '—' : `${n.toFixed(2)} Mbps` }
function mbs(n: number) { return n < 0.001 ? '—' : `${n.toFixed(2)} MB/s` }

// ─── CPU ──────────────────────────────────────────────────────────────────────

function CPUCard({ data }: { data: SystemData }) {
  const tc = data.cpuTemp >= 75 ? '#ff2222' : data.cpuTemp >= 60 ? '#aaaa00' : '#00ff88'
  return (
    <Card title="CPU UTILIZATION">
      <BigVal value={pct(data.cpuLoad)} color="var(--border-cyan)" />
      <Row label="Núcleos" value={String(data.cpuCores)} />
      <Row label="Temp" value={data.cpuTemp > 0 ? `${Math.round(data.cpuTemp)}°C` : '--'} color={tc} />
      <div style={{ flex: 1, minHeight: 0 }}>
        <LineChart data={data.cpuHistory} color="var(--border-cyan)" height={56} />
      </div>
    </Card>
  )
}

// ─── RAM ──────────────────────────────────────────────────────────────────────

function RAMCard({ data }: { data: SystemData }) {
  return (
    <Card title="RAM ALLOCATION">
      <BigVal value={gb(data.ramUsed)} color="var(--border-magenta)" />
      <Row label="Total" value={gb(data.ramTotal)} />
      <Row label="Uso" value={pct(data.ramPercent)} color="var(--border-magenta)" />
      <div style={{
        height: 14,
        background: '#111130',
        borderRadius: 2,
        overflow: 'hidden',
        border: '1px solid #ff00aa33',
        flexShrink: 0,
      }}>
        <div style={{
          height: '100%',
          width: `${Math.min(data.ramPercent, 100)}%`,
          background: 'var(--border-magenta)',
          boxShadow: '0 0 6px #ff00aa88',
          transition: 'width 0.4s',
        }} />
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <BarChart data={data.ramHistory} color="var(--border-magenta)" height={44} />
      </div>
    </Card>
  )
}

// ─── Network ──────────────────────────────────────────────────────────────────

function NetCard({ data }: { data: SystemData }) {
  const last = data.netHistory[data.netHistory.length - 1]
  const rxH  = data.netHistory.map(n => n.rx)
  const txH  = data.netHistory.map(n => n.tx)
  return (
    <Card title="NETWORK TRAFFIC">
      <div style={{ display: 'flex', gap: 16, flexShrink: 0 }}>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.1em' }}>DL</div>
          <MedVal value={last ? mbps(last.rx) : '—'} color="var(--border-cyan)" />
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.1em' }}>UL</div>
          <MedVal value={last ? mbps(last.tx) : '—'} color="var(--border-magenta)" />
        </div>
      </div>
      <Row label="Interfaz" value={data.netInterface} />
      <div style={{ flex: 1, minHeight: 0 }}>
        <LineChart
          data={rxH}  color="var(--border-cyan)"
          data2={txH} color2="var(--border-magenta)"
          height={70}
        />
      </div>
    </Card>
  )
}

// ─── Disk ─────────────────────────────────────────────────────────────────────

function DiskCard({ data }: { data: SystemData }) {
  const last   = data.diskHistory[data.diskHistory.length - 1]
  const rH     = data.diskHistory.map(d => d.r)
  const wH     = data.diskHistory.map(d => d.w)
  const usedPct = data.diskTotal > 0 ? (data.diskUsed / data.diskTotal) * 100 : 0
  const diskColor = usedPct > 85 ? '#ff2222' : usedPct > 70 ? '#aaaa00' : 'var(--border-cyan)'
  return (
    <Card title="DISK USAGE">
      <div style={{ display: 'flex', gap: 16, flexShrink: 0 }}>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.1em' }}>R</div>
          <MedVal value={last ? mbs(last.r) : '—'} color="var(--border-cyan)" />
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem', letterSpacing: '0.1em' }}>W</div>
          <MedVal value={last ? mbs(last.w) : '—'} color="var(--border-magenta)" />
        </div>
      </div>
      <Row label="/" value={data.diskTotal > 0 ? `${gb(data.diskUsed)} / ${gb(data.diskTotal)}` : '—'} />
      {data.diskTotal > 0 && (
        <div style={{
          height: 10,
          background: '#111130',
          borderRadius: 2,
          overflow: 'hidden',
          border: '1px solid #00f0ff33',
          flexShrink: 0,
        }}>
          <div style={{
            height: '100%',
            width: `${Math.min(usedPct, 100)}%`,
            background: diskColor,
            boxShadow: `0 0 6px ${diskColor}88`,
            transition: 'width 0.4s',
          }} />
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <LineChart
          data={rH}  color="var(--border-cyan)"
          data2={wH} color2="var(--border-magenta)"
          height={60}
        />
      </div>
    </Card>
  )
}

// ─── Export ───────────────────────────────────────────────────────────────────

export function MetricsRow({ data }: Props) {
  return (
    <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
      <CPUCard  data={data} />
      <RAMCard  data={data} />
      <NetCard  data={data} />
      <DiskCard data={data} />
    </div>
  )
}
