import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('windowControls', {
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close:    () => ipcRenderer.send('window:close'),
});

contextBridge.exposeInMainWorld('sityAPI', {
  getMetrics:     ()                  => ipcRenderer.invoke('metrics:get'),
  getServices:    ()                  => ipcRenderer.invoke('services:get'),
  getLog:         (name: string)      => ipcRenderer.invoke('service:log', name),
  restartService: (name: string)      => ipcRenderer.invoke('service:restart', name),
});
