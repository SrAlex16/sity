import { app, BrowserWindow, ipcMain } from 'electron';
import * as path from 'path';
import * as si from 'systeminformation';
import { execSync } from 'child_process';

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1140,
    height: 720,
    minWidth: 980,
    minHeight: 600,
    frame: false,
    backgroundColor: '#05070f',
    title: 'System Monitor [RO-01]',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'index.html'));

  mainWindow.once('ready-to-show', () => mainWindow?.show());

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// ---- Custom window controls ----
ipcMain.on('window:minimize', () => mainWindow?.minimize());

ipcMain.on('window:maximize', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});

ipcMain.on('window:close', () => mainWindow?.close());

// ---- System metrics ----
ipcMain.handle('metrics:get', async () => {
  const [load, mem, nets, disk, temp, procs] = await Promise.all([
    si.currentLoad(),
    si.mem(),
    si.networkStats(),
    si.disksIO(),
    si.cpuTemperature(),
    si.processes(),
  ]);

  const net = Array.isArray(nets) ? nets[0] : nets;

  return {
    cpu: {
      load: Math.round(load.currentLoad),
      temp: Math.round((temp.main as number | null) ?? 0),
    },
    ram: {
      used: mem.active,
      total: mem.total,
    },
    net: {
      dl: ((net as any)?.rx_sec ?? 0) * 8 / 1e6,
      ul: ((net as any)?.tx_sec ?? 0) * 8 / 1e6,
      iface: (net as any)?.iface ?? 'eth0',
    },
    disk: {
      r: (disk as any).rIO_sec ?? 0,
      w: (disk as any).wIO_sec ?? 0,
    },
    processes: procs.list
      .sort((a, b) => b.cpu - a.cpu)
      .slice(0, 60)
      .map(p => ({
        name: p.name,
        pid: p.pid,
        cpu: p.cpu,
        ram: Math.round(((p.memRss as number | null) ?? 0) / 1024),
        state: p.state,
      })),
    processCount: procs.all,
  };
});

// ---- Service status ----
ipcMain.handle('services:get', async () => {
  const check = (svc: string): string => {
    try {
      return execSync(`systemctl is-active ${svc}`, { encoding: 'utf8' }).trim();
    } catch {
      return 'inactive';
    }
  };
  return {
    'sity-backend': check('sity-backend'),
    'caddy': check('caddy'),
    'cloudflared': check('cloudflared'),
  };
});

// ---- Service journal log ----
ipcMain.handle('service:log', async (_event, name: string) => {
  try {
    return execSync(`journalctl -u ${name} -n 40 --no-pager`, { encoding: 'utf8' });
  } catch {
    return 'Log unavailable.';
  }
});
