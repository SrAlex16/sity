import { app, BrowserWindow, ipcMain } from 'electron'
import { execSync } from 'child_process'
import os from 'os'
import path from 'path'
import si from 'systeminformation'

const isDev = !app.isPackaged

let win: BrowserWindow | null = null
let dataInterval: ReturnType<typeof setInterval> | null = null

async function createWindow() {
  win = new BrowserWindow({
    width: 1920,
    height: 1080,
    frame: false,
    backgroundColor: '#0a0a14',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  win.maximize()

  if (isDev) {
    win.loadURL('http://localhost:5173')
  } else {
    win.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  // Window controls
  ipcMain.on('window-minimize', () => win?.minimize())
  ipcMain.on('window-close', () => win?.close())

  // Service status — read via systemctl
  ipcMain.handle('get-service-status', () => {
    const services = ['sity-backend', 'caddy', 'cloudflared']
    const result: Record<string, string> = {}
    for (const svc of services) {
      try {
        result[svc] = execSync(`systemctl is-active ${svc}`, { encoding: 'utf8' }).trim()
      } catch {
        // systemctl exits non-zero when service is inactive/failed
        result[svc] = 'inactive'
      }
    }
    return result
  })

  // Last 30 lines of journalctl for a service
  ipcMain.handle('get-service-log', (_event, service: string) => {
    try {
      return execSync(`journalctl -u ${service} -n 30 --no-pager`, { encoding: 'utf8' })
    } catch (e) {
      return `Error al leer log: ${e}`
    }
  })

  // Push system metrics to renderer every 2s
  async function pushData() {
    if (!win || win.isDestroyed()) return
    try {
      const [load, mem, net, disk, procs, temp, fs] = await Promise.all([
        si.currentLoad(),
        si.mem(),
        si.networkStats(),
        si.disksIO(),
        si.processes(),
        si.cpuTemperature(),
        si.fsSize(),
      ])
      win.webContents.send('system-data', {
        load,
        mem,
        net,
        disk,
        procs,
        temp,
        fs,
        uptimeSecs: os.uptime(),
      })
    } catch (_e) {
      // non-fatal: skip this tick
    }
  }

  await pushData()
  dataInterval = setInterval(pushData, 2000)
}

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
  if (dataInterval) clearInterval(dataInterval)
  if (process.platform !== 'darwin') app.quit()
})
