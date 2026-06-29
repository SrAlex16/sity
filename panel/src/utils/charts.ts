export function drawLineChart(
  canvas: HTMLCanvasElement,
  data: number[] | [number, number][],
  color1: string,
  color2?: string
) {
  const dpr = window.devicePixelRatio || 1
  const W = canvas.offsetWidth  * dpr
  const H = canvas.offsetHeight * dpr
  if (W === 0 || H === 0) return
  canvas.width  = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  ctx.clearRect(0, 0, W, H)

  const drawSeries = (vals: number[], color: string) => {
    if (vals.length < 2) return
    const max = Math.max(...vals, 1)
    ctx.beginPath()
    vals.forEach((v, i) => {
      const x = (i / (vals.length - 1)) * W
      const y = H - (v / max) * H * 0.88 - H * 0.06
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5 * dpr
    ctx.shadowColor = color
    ctx.shadowBlur  = 6 * dpr
    ctx.stroke()
    ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.closePath()
    ctx.fillStyle = color + '1a'
    ctx.fill()
    ctx.shadowBlur = 0
  }

  if (color2 && data.length > 0 && Array.isArray(data[0])) {
    drawSeries((data as [number, number][]).map(d => d[0]), color1)
    drawSeries((data as [number, number][]).map(d => d[1]), color2)
  } else {
    drawSeries(data as number[], color1)
  }
}
