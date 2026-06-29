/**
 * Renderer process — vanilla TypeScript, no module imports.
 * Compiled to dist/renderer.js and loaded via <script> tag.
 */
(() => {
  'use strict';

  // ----------------------------------------------------------
  // Window controls
  // ----------------------------------------------------------
  const wc = (window as any).windowControls as
    | { minimize(): void; maximize(): void; close(): void }
    | undefined;

  const onClick = (id: string, fn: () => void) =>
    document.getElementById(id)?.addEventListener('click', fn);

  if (wc) {
    onClick('btn-min',   () => wc.minimize());
    onClick('btn-max',   () => wc.maximize());
    onClick('btn-close', () => wc.close());
  }

  // ----------------------------------------------------------
  // sityAPI handle
  // ----------------------------------------------------------
  interface SityMetrics {
    cpu: { load: number; temp: number };
    ram: { used: number; total: number };
    net: { dl: number; ul: number; iface: string };
    disk: { r: number; w: number };
    processes: Array<{ name: string; pid: number; cpu: number; ram: number; state: string }>;
    processCount: number;
  }

  const api = (window as any).sityAPI as {
    getMetrics():  Promise<SityMetrics>;
    getServices(): Promise<Record<string, string>>;
    getLog(name: string): Promise<string>;
  } | undefined;

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------
  const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);

  function rgba(hex: string, a: number): string {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  const fmt = (n: number) => n.toLocaleString('en-US');

  const setText = (id: string, txt: string) => {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  };

  function escHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ----------------------------------------------------------
  // Theme colors
  // ----------------------------------------------------------
  const C = {
    cyan:    '#1fe7d6',
    purple:  '#a94bff',
    magenta: '#e24bff',
    blue:    '#3aa0ff',
    pink:    '#ff3d80',
    red:     '#ff3b5c',
  };

  // ----------------------------------------------------------
  // Score-based process color tiers
  // ----------------------------------------------------------
  function scoreColor(cpu: number, ramMb: number, totalMb: number): string {
    const ramPct = totalMb > 0 ? (ramMb / totalMb) * 100 : 0;
    const score = cpu * 0.7 + ramPct * 0.3;
    if (score > 25) return C.red;
    if (score > 12) return '#ff6b35';
    if (score > 7)  return C.pink;
    if (score > 4)  return C.purple;
    if (score > 2)  return C.blue;
    if (score > 0.5) return C.cyan;
    return '#1a4a5a';
  }

  // ----------------------------------------------------------
  // Real-data history arrays (updated by update() every 2s)
  // ----------------------------------------------------------
  const CPU_HIST:     number[] = Array(64).fill(0);
  const RAM_HIST:     number[] = Array(26).fill(0);
  const NET_DL_HIST:  number[] = Array(60).fill(0);
  const NET_UL_HIST:  number[] = Array(60).fill(0);
  const DISK_R_HIST:  number[] = Array(60).fill(0);
  const DISK_W_HIST:  number[] = Array(60).fill(0);

  let netMax  = 1;
  let diskMax = 1;
  let totalRamMb = 4096;   // updated on first real data

  // ----------------------------------------------------------
  // Canvas chart engine
  // ----------------------------------------------------------
  type Pad = { top: number; bottom: number };

  abstract class BaseChart {
    protected cvs: HTMLCanvasElement;
    protected ctx: CanvasRenderingContext2D;
    protected w = 0;
    protected h = 0;
    protected ok = false;

    constructor(id: string) {
      const el = document.getElementById(id) as HTMLCanvasElement | null;
      if (!el) { this.cvs = document.createElement('canvas'); this.ctx = this.cvs.getContext('2d')!; return; }
      this.cvs = el;
      this.ctx = el.getContext('2d')!;
      this.ok = true;
      this.resize();
    }

    resize(): void {
      if (!this.ok) return;
      const dpr = window.devicePixelRatio || 1;
      const r = this.cvs.getBoundingClientRect();
      this.w = Math.max(1, r.width);
      this.h = Math.max(1, r.height);
      this.cvs.width  = Math.floor(this.w * dpr);
      this.cvs.height = Math.floor(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    protected plot(
      data: number[],
      color: string,
      opts: { fill?: number; line?: number; glow?: number; pad?: Pad } = {}
    ): void {
      const { ctx, w, h } = this;
      const pad = opts.pad ?? { top: 8, bottom: 2 };
      const usable = h - pad.top - pad.bottom;
      const n = data.length;
      const X = (i: number) => (i / (n - 1)) * w;
      const Y = (v: number) => pad.top + (1 - v) * usable;

      if (opts.fill) {
        ctx.beginPath();
        ctx.moveTo(0, h);
        for (let i = 0; i < n; i++) ctx.lineTo(X(i), Y(data[i]));
        ctx.lineTo(w, h);
        ctx.closePath();
        const g = ctx.createLinearGradient(0, 0, 0, h);
        g.addColorStop(0, rgba(color, opts.fill));
        g.addColorStop(1, rgba(color, 0));
        ctx.fillStyle = g;
        ctx.fill();
      }

      ctx.beginPath();
      for (let i = 0; i < n; i++) {
        const x = X(i), y = Y(data[i]);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.lineWidth = opts.line ?? 1.6;
      ctx.lineJoin = 'round';
      ctx.strokeStyle = color;
      if (opts.glow) { ctx.shadowColor = color; ctx.shadowBlur = opts.glow; }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    abstract render(): void;
  }

  class CpuChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      this.plot(CPU_HIST, C.cyan, { fill: 0.30, line: 1.7, glow: 7 });
    }
  }

  class RamChart extends BaseChart {
    render() {
      if (!this.ok) return;
      const { ctx, w, h } = this;
      ctx.clearRect(0, 0, w, h);
      const n = RAM_HIST.length;
      const padB = 2, usable = h - padB - 2;
      const slot = w / n, bw = slot * 0.6;
      for (let i = 0; i < n; i++) {
        const v = Math.max(0.04, RAM_HIST[i]);
        const bh = v * usable;
        const x = i * slot + (slot - bw) / 2;
        const y = h - padB - bh;
        const g = ctx.createLinearGradient(0, y, 0, h);
        g.addColorStop(0, C.magenta);
        g.addColorStop(1, rgba(C.purple, 0.85));
        ctx.fillStyle = g;
        ctx.shadowColor = C.magenta;
        ctx.shadowBlur = 8;
        const r = Math.min(2.5, bw / 2);
        ctx.beginPath();
        ctx.moveTo(x, y + r);
        ctx.arcTo(x, y, x + r, y, r);
        ctx.lineTo(x + bw - r, y);
        ctx.arcTo(x + bw, y, x + bw, y + r, r);
        ctx.lineTo(x + bw, h - padB);
        ctx.lineTo(x, h - padB);
        ctx.closePath();
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }
  }

  class NetChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      this.plot(NET_DL_HIST, C.blue, { fill: 0.28, line: 1.6, glow: 7 });
      this.plot(NET_UL_HIST, C.pink, { line: 1.5, glow: 6 });
    }
  }

  class DiskChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      this.plot(DISK_R_HIST, C.pink, { fill: 0.32, line: 1.7, glow: 7 });
      this.plot(DISK_W_HIST, C.blue, { line: 1.3, glow: 5 });
    }
  }

  const charts: BaseChart[] = [
    new CpuChart('chart-cpu'),
    new RamChart('chart-ram'),
    new NetChart('chart-net'),
    new DiskChart('chart-disk'),
  ];

  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => charts.forEach(c => c.resize()), 120);
  });

  // Animation loop (~18 fps)
  let last = 0;
  function loop(t: number): void {
    if (t - last >= 55) {
      last = t;
      for (const c of charts) c.render();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  // ----------------------------------------------------------
  // Background hex mesh
  // ----------------------------------------------------------
  const bg = document.getElementById('bg-hex') as HTMLCanvasElement | null;

  function drawHex(ctx: CanvasRenderingContext2D, cx: number, cy: number, s: number): void {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const ang = (Math.PI / 180) * (60 * i - 90);
      const px = cx + s * Math.cos(ang);
      const py = cy + s * Math.sin(ang);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.stroke();
  }

  function drawHexGrid(): void {
    if (!bg) return;
    const ctx = bg.getContext('2d')!;
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    bg.width  = Math.floor(w * dpr);
    bg.height = Math.floor(h * dpr);
    bg.style.width  = w + 'px';
    bg.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const s  = 26;
    const hw = Math.sqrt(3) * s;
    ctx.strokeStyle = 'rgba(46,130,150,0.10)';
    ctx.lineWidth = 1;

    let row = -1;
    for (let y = -s; y < h + s; row++, y = row * 1.5 * s) {
      const offset = row % 2 ? hw / 2 : 0;
      for (let x = -hw; x < w + hw; x += hw) drawHex(ctx, x + offset, y, s);
    }
  }
  drawHexGrid();
  window.addEventListener('resize', drawHexGrid);

  // ----------------------------------------------------------
  // Process list rendering
  // ----------------------------------------------------------
  function renderProcs(
    procs: SityMetrics['processes'],
    total: number,
    totalRamBytes: number
  ): void {
    const list = document.getElementById('proc-list');
    if (!list) return;
    const tMb = totalRamBytes / 1024 / 1024;
    list.innerHTML = procs.map(p => {
      const color = scoreColor(p.cpu, p.ram, tMb);
      const icon  = p.name.charAt(0).toUpperCase();
      const state = p.state === 'running'  ? 'Running'
                  : p.state === 'sleeping' ? 'Sleep'
                  : p.state || '–';
      return `<div class="row" style="--c:${color}">
        <span class="cell cell--icon">[${icon}]</span>
        <span class="cell cell--name">${escHtml(p.name)}</span>
        <span class="cell cell--num">${p.pid}</span>
        <span class="cell cell--num">${p.cpu.toFixed(1)}%</span>
        <span class="cell cell--num">${p.ram} MB</span>
        <span class="cell cell--status">${escHtml(state)}</span>
        <span class="cell cell--state">/proc/${p.pid}</span>
      </div>`;
    }).join('');

    setText('panel-title', `ACTIVE PROCESSES // ${total} TOTAL`);
  }

  // ----------------------------------------------------------
  // Alert overlay
  // ----------------------------------------------------------
  let alertOpen = false;

  function showAlert(title: string, msg: string): void {
    setText('alert-title', title);
    setText('alert-msg', msg);
    const overlay = document.getElementById('alert-overlay');
    if (overlay) overlay.classList.add('visible');
    alertOpen = true;
  }

  function closeAlert(): void {
    const overlay = document.getElementById('alert-overlay');
    if (overlay) overlay.classList.remove('visible');
    alertOpen = false;
  }

  document.getElementById('alert-close')?.addEventListener('click', closeAlert);

  // ----------------------------------------------------------
  // Services bar
  // ----------------------------------------------------------
  const SVC_MAP: Record<string, string> = {
    'sity-backend': 'svc-backend',
    'caddy':        'svc-caddy',
    'cloudflared':  'svc-cloudflared',
  };

  // Wire log-click handlers once at startup
  if (api) {
    for (const [name, domId] of Object.entries(SVC_MAP)) {
      document.getElementById(domId)?.addEventListener('click', async () => {
        const log = await api.getLog(name);
        showAlert(name.toUpperCase() + ' // JOURNAL', log || 'No log data.');
      });
    }
  }

  let inactiveAlertFired = false;

  async function updateServices(): Promise<void> {
    if (!api) return;
    try {
      const svcs = await api.getServices();
      let anyInactive = false;
      for (const [name, domId] of Object.entries(SVC_MAP)) {
        const status = svcs[name] ?? 'unknown';
        const el = document.getElementById(domId);
        if (!el) continue;
        el.className = 'svc ' + (status === 'active' ? 'active' : 'inactive');
        const statusEl = el.querySelector('.svc__status');
        if (statusEl) statusEl.textContent = status;
        if (status !== 'active') anyInactive = true;
      }
      if (anyInactive && !inactiveAlertFired && !alertOpen) {
        inactiveAlertFired = true;
        const down = Object.entries(svcs)
          .filter(([, s]) => s !== 'active')
          .map(([n, s]) => `  ${n}: ${s}`)
          .join('\n');
        showAlert('SERVICE ALERT', `One or more services are not active:\n\n${down}`);
      }
    } catch (e) {
      console.error('services error:', e);
    }
  }

  // ----------------------------------------------------------
  // Main metrics update
  // ----------------------------------------------------------
  async function update(): Promise<void> {
    if (!api) return;
    try {
      const m = await api.getMetrics();

      // CPU
      CPU_HIST.push(clamp(m.cpu.load / 100, 0, 1));
      CPU_HIST.shift();
      setText('cpu-pct',  m.cpu.load + '%');
      setText('cpu-load', m.cpu.load + '%');
      setText('cpu-temp', m.cpu.temp > 0 ? m.cpu.temp + '°C' : '–');

      // RAM
      const totalRamBytes = m.ram.total;
      totalRamMb = totalRamBytes / 1024 / 1024;
      const ramNorm = clamp(m.ram.used / totalRamBytes, 0, 1);
      RAM_HIST.push(ramNorm);
      RAM_HIST.shift();
      const usedMb  = Math.round(m.ram.used  / 1024 / 1024);
      const totalGb = (totalRamBytes / 1024 / 1024 / 1024).toFixed(1);
      const ramPct  = Math.round(ramNorm * 100);
      setText('ram-pct',  ramPct + '%');
      setText('ram-mem',  (usedMb / 1024).toFixed(1) + ' GB');
      setText('ram-used', fmt(usedMb) + ' MB');
      const ramSub = document.getElementById('ram-sub');
      if (ramSub) ramSub.innerHTML =
        `MEMORY: <span id="ram-mem">${(usedMb / 1024).toFixed(1)} GB</span> / ${totalGb} GB`;

      // Network
      const dl = m.net.dl, ul = m.net.ul;
      netMax = Math.max(netMax, dl, ul, 1);
      NET_DL_HIST.push(dl / netMax); NET_DL_HIST.shift();
      NET_UL_HIST.push(ul / netMax); NET_UL_HIST.shift();
      setText('net-dl',   dl.toFixed(2) + ' Mbps');
      setText('net-ul',   ul.toFixed(2) + ' Mbps');
      setText('net-iface', m.net.iface);

      // Disk
      const dr = m.disk.r, dw = m.disk.w;
      diskMax = Math.max(diskMax, dr, dw, 1);
      DISK_R_HIST.push(dr / diskMax); DISK_R_HIST.shift();
      DISK_W_HIST.push(dw / diskMax); DISK_W_HIST.shift();
      setText('disk-r', Math.round(dr) + ' IO/s');
      setText('disk-w', Math.round(dw) + ' IO/s');

      // Processes
      renderProcs(m.processes, m.processCount, totalRamBytes);

    } catch (e) {
      console.error('update error:', e);
    }
  }

  // ----------------------------------------------------------
  // Polling intervals
  // ----------------------------------------------------------
  update();
  updateServices();
  setInterval(update, 2000);
  setInterval(updateServices, 8000);
})();
