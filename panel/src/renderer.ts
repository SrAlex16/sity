/**
 * Renderer process — vanilla TypeScript, IIFE, no module imports.
 * Chart engine preserved from the original design.
 * Data driven by sityAPI (contextBridge) instead of random-walk mocks.
 */
(() => {
  'use strict';

  // ----------------------------------------------------------
  // Typed handles for contextBridge APIs
  // ----------------------------------------------------------
  interface SityAPI {
    getMetrics():  Promise<MetricsData>;
    getServices(): Promise<Record<string, string>>;
    getLog(name: string): Promise<string>;
    restartService(name: string): Promise<string>;
  }
  interface WindowControls {
    minimize(): void; maximize(): void; close(): void;
  }
  interface MetricsData {
    cpu: { load: number; temp: number; cores: number; threads: number };
    ram: { used: number; total: number };
    net: { dl: number; ul: number; iface: string };
    disk: { r: number; w: number };
    processes: Array<{ name: string; pid: number; cpu: number; ram: number; state: string }>;
    processCount: number;
  }

  const api = (window as any).sityAPI as SityAPI | undefined;
  const wc  = (window as any).windowControls as WindowControls | undefined;

  // ----------------------------------------------------------
  // Window controls
  // ----------------------------------------------------------
  const onClick = (id: string, fn: () => void) =>
    document.getElementById(id)?.addEventListener('click', fn);

  if (wc) {
    onClick('btn-min',   () => wc.minimize());
    onClick('btn-max',   () => wc.maximize());
    onClick('btn-close', () => wc.close());
  }

  // ----------------------------------------------------------
  // Small helpers
  // ----------------------------------------------------------
  const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);

  function rgba(hex: string, a: number): string {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  const setText = (id: string, txt: string) => {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  };

  function escHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ----------------------------------------------------------
  // Theme colors (in sync with styles.css)
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
  // Icon set for process location column
  // ----------------------------------------------------------
  const ICONS: Record<string, string> = {
    globe:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.6 2.7 2.6 15.3 0 18M12 3c-2.6 2.7-2.6 15.3 0 18"/></svg>`,
    gear:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2.1 2.1M16.9 16.9 19 19M19 5l-2.1 2.1M7.1 16.9 5 19"/></svg>`,
    lock:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>`,
    palette: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 3a9 9 0 0 0 0 18c1.2 0 2-.9 2-2 0-.5-.2-.9-.5-1.3-.3-.4-.5-.7-.5-1.1 0-.8.7-1.5 1.6-1.5H16a5 5 0 0 0 5-5c0-3.9-4-7-9-7Z"/><circle cx="7.6" cy="11.5" r="1" fill="currentColor" stroke="none"/><circle cx="11" cy="7.6" r="1" fill="currentColor" stroke="none"/><circle cx="15.2" cy="8.6" r="1" fill="currentColor" stroke="none"/></svg>`,
    brain:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 4A2.5 2.5 0 0 0 7 6.5 3 3 0 0 0 5 12a3 3 0 0 0 2 5.2A2.8 2.8 0 0 0 12 18V5.5A1.5 1.5 0 0 0 10.5 4Z"/><path d="M14.5 4A2.5 2.5 0 0 1 17 6.5 3 3 0 0 1 19 12a3 3 0 0 1-2 5.2A2.8 2.8 0 0 1 12 18"/></svg>`,
    sat:     `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M5 19l5.5-5.5"/><circle cx="5" cy="19" r="1.3"/><path d="M11 6.5a8.5 8.5 0 0 1 6.5 6.5"/><path d="M11 10.5a4.2 4.2 0 0 1 2.2 2.2"/></svg>`,
  };

  // ----------------------------------------------------------
  // Process location inference
  // ----------------------------------------------------------
  function inferLoc(name: string): string {
    if (/python3|uvicorn/i.test(name))                    return '/Runtime';
    if (/caddy|cloudflared|sshd|nginx|ngrok/i.test(name)) return '/Network';
    if (/labwc|Xwayland|wayfire|waybar/i.test(name))      return '/Display';
    if (/kworker|rcu_|ksoftirqd|kthread/i.test(name))     return '/Kernel';
    if (/claude|bash|^sh$|zsh/i.test(name))               return '/Shell';
    return '/System';
  }

  function inferLocIcon(name: string): keyof typeof ICONS {
    if (/python3|uvicorn/i.test(name))                    return 'brain';
    if (/caddy|cloudflared|sshd|nginx|ngrok/i.test(name)) return 'globe';
    if (/labwc|Xwayland|wayfire|waybar/i.test(name))      return 'palette';
    if (/kworker|rcu_|ksoftirqd|kthread/i.test(name))     return 'gear';
    if (/claude|bash|^sh$|zsh/i.test(name))               return 'lock';
    return 'gear';
  }

  // ----------------------------------------------------------
  // Score-based process color tiers
  // ----------------------------------------------------------
  function scoreColor(cpu: number, ramMb: number, totalMb: number): string {
    const ramPct = totalMb > 0 ? (ramMb / totalMb) * 100 : 0;
    const score  = cpu * 0.7 + ramPct * 0.3;
    if (score >  80) return '#ff3b5c';
    if (score >  60) return '#cc6600';
    if (score >  40) return '#cccc00';
    if (score >  20) return '#44bb44';
    if (score >   8) return C.cyan;
    if (score >   2) return '#00aacc';
    return '#1a3a4a';
  }

  // Processes from Sity's own stack get a magenta outline
  const SITY_PROCS = new Set(['python3', 'uvicorn', 'caddy', 'cloudflared']);

  // ----------------------------------------------------------
  // Real-data history arrays (pushed by update() every 2s)
  // ----------------------------------------------------------
  const CPU_HIST:  number[]           = Array(60).fill(0);
  const RAM_HIST:  number[]           = Array(60).fill(0);
  const NET_HIST:  [number, number][] = Array.from({ length: 60 }, () => [0, 0]);
  const DISK_HIST: [number, number][] = Array.from({ length: 60 }, () => [0, 0]);

  let netMax  = 1;
  let diskMax = 1;

  // ----------------------------------------------------------
  // Canvas chart engine (preserved from original design)
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
      if (!el) {
        this.cvs = document.createElement('canvas');
        this.ctx = this.cvs.getContext('2d')!;
        return;
      }
      this.cvs = el;
      this.ctx = el.getContext('2d')!;
      this.ok  = true;
      this.resize();
    }

    resize(): void {
      if (!this.ok) return;
      const dpr = window.devicePixelRatio || 1;
      const r   = this.cvs.getBoundingClientRect();
      this.w    = Math.max(1, r.width);
      this.h    = Math.max(1, r.height);
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
      const pad    = opts.pad ?? { top: 8, bottom: 2 };
      const usable = h - pad.top - pad.bottom;
      const n      = data.length;
      const X      = (i: number) => (i / (n - 1)) * w;
      const Y      = (v: number) => pad.top + (1 - v) * usable;

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
      ctx.lineWidth  = opts.line ?? 1.6;
      ctx.lineJoin   = 'round';
      ctx.strokeStyle = color;
      if (opts.glow) { ctx.shadowColor = color; ctx.shadowBlur = opts.glow; }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    abstract render(): void;
  }

  // CPU: cyan area chart (normalized 0-100 → 0-1)
  class CpuChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      const norm = CPU_HIST.map(v => clamp(v / 100, 0, 1));
      this.plot(norm, C.cyan, { fill: 0.30, line: 1.7, glow: 7 });
    }
  }

  // RAM: ascending glowing bars (last 26 history samples)
  class RamChart extends BaseChart {
    render() {
      if (!this.ok) return;
      const { ctx, w, h } = this;
      ctx.clearRect(0, 0, w, h);
      const bars   = RAM_HIST.slice(-26).map(v => Math.max(0.04, clamp(v / 100, 0, 1)));
      const n      = bars.length;
      const padB   = 2, usable = h - padB - 2;
      const slot   = w / n, bw = slot * 0.6;
      for (let i = 0; i < n; i++) {
        const bh = bars[i] * usable;
        const x  = i * slot + (slot - bw) / 2;
        const y  = h - padB - bh;
        const g  = ctx.createLinearGradient(0, y, 0, h);
        g.addColorStop(0, C.magenta);
        g.addColorStop(1, rgba(C.purple, 0.85));
        ctx.fillStyle  = g;
        ctx.shadowColor = C.magenta;
        ctx.shadowBlur  = 8;
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

  // Network: blue DL area + pink UL line (auto-scaled)
  class NetChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      const max = Math.max(netMax, 1);
      const dl  = NET_HIST.map(([d]) => clamp(d / max, 0, 1));
      const ul  = NET_HIST.map(([, u]) => clamp(u / max, 0, 1));
      this.plot(dl, C.blue, { fill: 0.28, line: 1.6, glow: 7 });
      this.plot(ul, C.pink, { line: 1.5, glow: 6 });
    }
  }

  // Disk: pink R area + blue W line (auto-scaled)
  class DiskChart extends BaseChart {
    render() {
      if (!this.ok) return;
      this.ctx.clearRect(0, 0, this.w, this.h);
      const max = Math.max(diskMax, 1);
      const r   = DISK_HIST.map(([rv]) => clamp(rv / max, 0, 1));
      const w2  = DISK_HIST.map(([, wv]) => clamp(wv / max, 0, 1));
      this.plot(r,  C.pink, { fill: 0.32, line: 1.7, glow: 7 });
      this.plot(w2, C.blue, { line: 1.3, glow: 5 });
    }
  }

  const cpuChart  = new CpuChart('chart-cpu');
  const ramChart  = new RamChart('chart-ram');
  const netChart  = new NetChart('chart-net');
  const diskChart = new DiskChart('chart-disk');
  const allCharts = [cpuChart, ramChart, netChart, diskChart];

  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => allCharts.forEach(c => c.resize()), 120);
  });

  // Animation loop (~18 fps)
  let last = 0;
  function loop(t: number): void {
    if (t - last >= 55) {
      last = t;
      for (const c of allCharts) c.render();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  // ----------------------------------------------------------
  // Background hex mesh (painted once, redrawn on resize)
  // ----------------------------------------------------------
  const bg = document.getElementById('bg-hex') as HTMLCanvasElement | null;

  function drawHex(ctx: CanvasRenderingContext2D, cx: number, cy: number, s: number): void {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const ang = (Math.PI / 180) * (60 * i - 90);
      const px  = cx + s * Math.cos(ang);
      const py  = cy + s * Math.sin(ang);
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.stroke();
  }

  function drawHexGrid(): void {
    if (!bg) return;
    const ctx = bg.getContext('2d')!;
    const dpr = window.devicePixelRatio || 1;
    const w   = window.innerWidth;
    const h   = window.innerHeight;
    bg.width  = Math.floor(w * dpr);
    bg.height = Math.floor(h * dpr);
    bg.style.width  = w + 'px';
    bg.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const s  = 26;
    const hw = Math.sqrt(3) * s;
    ctx.strokeStyle = 'rgba(46,130,150,0.10)';
    ctx.lineWidth   = 1;

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
  function renderProcesses(
    procs: MetricsData['processes'],
    total: number,
    totalRamBytes: number
  ): void {
    const list = document.getElementById('proc-list');
    if (!list) return;
    const totalMb = totalRamBytes / 1e6;

    list.innerHTML = procs.map(p => {
      const color  = scoreColor(p.cpu, p.ram, totalMb);
      const icon   = escHtml(p.name.charAt(0).toUpperCase());
      const loc    = inferLoc(p.name);
      const locKey = inferLocIcon(p.name);
      const isSity = SITY_PROCS.has(p.name);
      const state  = p.state === 'running'  ? 'Running'
                   : p.state === 'sleeping' ? 'Sleep'
                   : escHtml(p.state || '–');
      return `<div class="row${isSity ? ' row--sity' : ''}" style="--c:${color}">
        <span class="cell cell--icon">[${icon}]</span>
        <span class="cell cell--name">${escHtml(p.name)}</span>
        <span class="cell cell--num">${p.pid}</span>
        <span class="cell cell--num">${p.cpu.toFixed(1)}%</span>
        <span class="cell cell--num">${p.ram} MB</span>
        <span class="cell cell--status">${state}</span>
        <span class="cell cell--loc">${ICONS[locKey] ?? ICONS.gear}<span>${loc}</span></span>
      </div>`;
    }).join('');

    const panelTitle = document.querySelector('.panel__title');
    if (panelTitle) panelTitle.textContent = `ACTIVE PROCESSES // ${total} TOTAL`;
  }

  // ----------------------------------------------------------
  // Error modal
  // ----------------------------------------------------------
  const backdrop   = document.getElementById('error-backdrop');
  const logBox     = document.getElementById('modal-log');
  const btnRestart = document.getElementById('modal-restart');
  const btnOk      = document.getElementById('modal-ok');

  let alertShown   = false;
  let lastBackendOk = true;

  function classifyLine(line: string): 'err' | 'warn' | 'info' {
    const l = line.toLowerCase();
    if (/error|critical|fail|exception|traceback/i.test(l)) return 'err';
    if (/warn|warning/i.test(l))                            return 'warn';
    return 'info';
  }

  function openErrorModal(logText?: string): void {
    if (!backdrop || !logBox) return;
    logBox.innerHTML = '';
    if (logText) {
      const lines = logText.split('\n').filter(l => l.trim());
      for (const line of lines) {
        const div = document.createElement('div');
        div.className = `log-line log-line--${classifyLine(line)}`;
        div.textContent = line;
        logBox.appendChild(div);
      }
      logBox.scrollTop = logBox.scrollHeight;
      const lastLine = logBox.lastElementChild;
      if (lastLine) lastLine.classList.add('log-line--cursor');
    }
    backdrop.classList.add('visible');
  }

  function closeErrorModal(): void {
    backdrop?.classList.remove('visible');
  }

  function handleRestart(): void {
    if (!logBox || !api) return;
    logBox.querySelector('.log-line--cursor')?.classList.remove('log-line--cursor');

    const addLine = (type: 'err' | 'warn' | 'info', text: string) => {
      const div = document.createElement('div');
      div.className = `log-line log-line--${type}`;
      div.textContent = text;
      logBox.appendChild(div);
      logBox.scrollTop = logBox.scrollHeight;
    };

    addLine('info', '[SYS] Initiating sity-backend restart...');

    api.restartService('sity-backend').then(result => {
      if (result !== 'ok') {
        addLine('warn', `[SYS] systemctl said: ${result}`);
      }
      setTimeout(async () => {
        const svcs2 = await api.getServices();
        if (svcs2['sity-backend'] === 'active') {
          const ok = document.createElement('div');
          ok.className = 'log-line log-line--info log-line--cursor';
          ok.textContent = '[BE-SYNC] sity-backend restarted successfully. Resuming.';
          logBox.appendChild(ok);
          logBox.scrollTop = logBox.scrollHeight;
          alertShown    = false;
          lastBackendOk = true;
          setTimeout(closeErrorModal, 1500);
        } else {
          const log2 = await api.getLog('sity-backend');
          addLine('err', '[FAIL] Restart did not bring the service up. New log:');
          for (const l of log2.split('\n').filter(Boolean).slice(-10)) {
            addLine(classifyLine(l), l);
          }
        }
      }, 3000);
    }).catch((e: unknown) => {
      addLine('err', `[ERR] ${String(e)}`);
    });
  }

  btnOk?.addEventListener('click', () => {
    closeErrorModal();
    alertShown = false;
  });
  btnRestart?.addEventListener('click', handleRestart);
  backdrop?.addEventListener('click', e => {
    if (e.target === backdrop) closeErrorModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeErrorModal();
  });

  // Dev helper: Ctrl+Shift+E or window.showError() to test modal
  (window as any).showError = () => openErrorModal('Test modal — no real error.');
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && e.shiftKey && e.key === 'E') openErrorModal('Test modal — no real error.');
  });

  // ----------------------------------------------------------
  // Services poll — only fires modal when sity-backend goes down
  // ----------------------------------------------------------
  async function updateServices(): Promise<void> {
    if (!api) return;
    try {
      const svcs = await api.getServices();
      const backendOk = svcs['sity-backend'] === 'active';
      if (!backendOk && lastBackendOk && !alertShown) {
        alertShown = true;
        const log  = await api.getLog('sity-backend');
        openErrorModal(log || 'No log output available.');
      }
      lastBackendOk = backendOk;
    } catch (e) {
      console.error('services error:', e);
    }
  }

  // ----------------------------------------------------------
  // Main metrics update (every 2s)
  // ----------------------------------------------------------
  async function update(): Promise<void> {
    if (!api) return;
    try {
      const data = await api.getMetrics();

      // CPU
      setText('cpu-pct',  `${data.cpu.load}%`);
      setText('cpu-load', `${data.cpu.load}%`);
      setText('cpu-temp', data.cpu.temp > 0 ? `${data.cpu.temp}°C` : '–');
      setText('cpu-cores', `${data.cpu.cores} Cores / ${data.cpu.threads} Threads`);
      CPU_HIST.push(data.cpu.load);
      CPU_HIST.shift();

      // RAM
      const usedGB  = (data.ram.used  / 1e9).toFixed(1);
      const totalGB = (data.ram.total / 1e9).toFixed(1);
      const ramPct  = Math.round(data.ram.used / data.ram.total * 100);
      setText('ram-pct',  `${ramPct}%`);
      setText('ram-used', `${Math.round(data.ram.used / 1e6).toLocaleString()} MB`);
      const ramSub = document.getElementById('ram-sub');
      if (ramSub) ramSub.innerHTML =
        `MEMORY: <span id="ram-mem">${usedGB} GB</span> / ${totalGB} GB`;
      RAM_HIST.push(ramPct);
      RAM_HIST.shift();

      // Network
      setText('net-dl',   `${data.net.dl.toFixed(2)} Mbps`);
      setText('net-ul',   `${data.net.ul.toFixed(2)} Mbps`);
      setText('net-iface', data.net.iface);
      netMax = Math.max(netMax, data.net.dl, data.net.ul, 1);
      NET_HIST.push([data.net.dl, data.net.ul]);
      NET_HIST.shift();

      // Disk
      setText('disk-r', `${data.disk.r} IO/s`);
      setText('disk-w', `${data.disk.w} IO/s`);
      diskMax = Math.max(diskMax, data.disk.r, data.disk.w, 1);
      DISK_HIST.push([data.disk.r, data.disk.w]);
      DISK_HIST.shift();

      // Processes
      renderProcesses(data.processes, data.processCount, data.ram.total);

    } catch (e) {
      console.error('update error:', e);
    }
  }

  // ----------------------------------------------------------
  // Start polling
  // ----------------------------------------------------------
  update();
  updateServices();
  setInterval(update, 2000);
  setInterval(updateServices, 8000);

})();
