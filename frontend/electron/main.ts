import { app, BrowserWindow, desktopCapturer, ipcMain, session, shell } from 'electron'
import * as path from 'path'
import { startPythonBackend, stopPythonBackend } from './python-manager'

const isDev = process.env.NODE_ENV === 'development'
const BACKEND_PORT = 8765
const FRONTEND_DIR = path.resolve(__dirname, '..')
const WEB_APP_DIR = path.resolve(FRONTEND_DIR, '..')

type BackendStartupStatus =
  | { state: 'starting'; port: number; error: null }
  | { state: 'ready'; port: number; error: null }
  | { state: 'error'; port: number; error: string }

let backendStatus: BackendStartupStatus = {
  state: 'starting',
  port: BACKEND_PORT,
  error: null,
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

function configureDesktopLoopback(): void {
  session.defaultSession.setDisplayMediaRequestHandler(async (_request, callback) => {
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: 0, height: 0 },
      fetchWindowIcons: false,
    })

    if (sources.length === 0) {
      callback({})
      return
    }

    callback({
      video: sources[0],
      // Electron's supported Windows system-audio path grants a screen
      // stream plus loopback audio. The renderer requests both, then
      // reads only the audio track.
      audio: 'loopback',
    })
  })
}

async function createWindow(): Promise<void> {
  console.log('[main] Starting Python backend...')
  backendStatus = { state: 'starting', port: BACKEND_PORT, error: null }
  try {
    await startPythonBackend(WEB_APP_DIR)
    backendStatus = { state: 'ready', port: BACKEND_PORT, error: null }
    console.log('[main] Backend ready')
  } catch (err) {
    backendStatus = { state: 'error', port: BACKEND_PORT, error: errorMessage(err) }
    console.error('[main] Backend failed to start:', err)
  }

  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    await win.loadURL('http://127.0.0.1:5173')
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    await win.loadFile(path.join(FRONTEND_DIR, 'dist', 'index.html'))
  }
}

ipcMain.handle('get-backend-port', () => BACKEND_PORT)

ipcMain.handle('get-backend-status', () => backendStatus)

ipcMain.handle('open-path', (_event, p: string) => shell.openPath(p))

app.whenReady().then(() => {
  configureDesktopLoopback()
  void createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow()
  })
})

app.on('before-quit', () => {
  stopPythonBackend()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    stopPythonBackend()
    app.quit()
  }
})
