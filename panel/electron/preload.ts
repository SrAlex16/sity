import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  onSystemData: (callback: (data: unknown) => void) => {
    ipcRenderer.on('system-data', (_event, data) => callback(data))
  },
  removeSystemDataListener: () => {
    ipcRenderer.removeAllListeners('system-data')
  },
  getServiceStatus: (): Promise<Record<string, string>> =>
    ipcRenderer.invoke('get-service-status'),
  getServiceLog: (service: string): Promise<string> =>
    ipcRenderer.invoke('get-service-log', service),
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  closeWindow: () => ipcRenderer.send('window-close'),
})
