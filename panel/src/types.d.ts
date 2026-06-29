export interface ProcessInfo {
  pid: number
  ppid?: number
  name: string
  cpu: number
  memRss: number   // MB
  state: string
}

export interface NetworkSample {
  rx: number  // Mbps
  tx: number  // Mbps
}

export interface DiskSample {
  r: number   // MB/s
  w: number   // MB/s
}

export interface SystemData {
  cpuLoad: number
  cpuHistory: number[]
  cpuTemp: number
  cpuCores: number
  ramUsed: number
  ramTotal: number
  ramPercent: number
  ramHistory: number[]
  netHistory: NetworkSample[]
  netInterface: string
  diskHistory: DiskSample[]
  diskUsed: number
  diskTotal: number
  processes: ProcessInfo[]
  uptimeSecs: number
}

interface ElectronAPI {
  onSystemData: (callback: (data: unknown) => void) => void
  removeSystemDataListener: () => void
  getServiceStatus: () => Promise<Record<string, string>>
  getServiceLog: (service: string) => Promise<string>
  minimizeWindow: () => void
  closeWindow: () => void
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}
