import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendPort: (): Promise<number> => ipcRenderer.invoke('get-backend-port'),
  getBackendStatus: (): Promise<{
    state: 'starting' | 'ready' | 'error'
    port: number
    error: string | null
  }> => ipcRenderer.invoke('get-backend-status'),
  platform: process.platform,
  enableLoopbackAudio: (): Promise<void> => ipcRenderer.invoke('enable-loopback-audio'),
  disableLoopbackAudio: (): Promise<void> => ipcRenderer.invoke('disable-loopback-audio'),
  openPath: (p: string): Promise<void> => ipcRenderer.invoke('open-path', p),
})
