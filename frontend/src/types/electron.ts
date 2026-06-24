export type BackendStartupStatus = {
  state: 'starting' | 'ready' | 'error'
  port: number
  error: string | null
}

export interface ElectronAPI {
  getBackendPort: () => Promise<number>
  getBackendStatus: () => Promise<BackendStartupStatus>
  platform?: string
  openPath: (path: string) => Promise<void>
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}
