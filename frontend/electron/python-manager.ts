import { ChildProcess, spawn } from 'child_process'
import * as http from 'http'
import * as fs from 'fs'
import * as path from 'path'

const BACKEND_PORT = 8765
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`
const MAX_ATTEMPTS = 40
const INTERVAL_MS = 500

let pythonProc: ChildProcess | null = null

function resolvePythonCommand(webAppDir: string): string {
  if (process.env.VOICE_DIARY_PYTHON) {
    return process.env.VOICE_DIARY_PYTHON
  }

  const candidates = [
    path.join(webAppDir, '.venv-ml', 'Scripts', 'python.exe'),
    path.join(webAppDir, '.venv-ml', 'bin', 'python'),
    path.join(webAppDir, '.venv', 'Scripts', 'python.exe'),
    path.join(webAppDir, '.venv', 'bin', 'python'),
  ]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }

  return process.platform === 'win32' ? 'python' : 'python3'
}

function healthCheck(): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(HEALTH_URL, (res) => {
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(400, () => { req.destroy(); resolve(false) })
  })
}

function waitUntilReady(maxAttempts: number): Promise<void> {
  return new Promise((resolve, reject) => {
    let attempts = 0
    const check = async () => {
      attempts++
      const ok = await healthCheck()
      if (ok) return resolve()
      if (attempts >= maxAttempts) return reject(new Error(`Backend did not start after ${maxAttempts} attempts`))
      setTimeout(check, INTERVAL_MS)
    }
    void check()
  })
}

export async function startPythonBackend(webAppDir: string): Promise<void> {
  // Check if backend is already running (e.g., started externally)
  if (await healthCheck()) return

  const isDev = process.env.NODE_ENV === 'development'

  if (isDev) {
    const pythonCommand = resolvePythonCommand(webAppDir)
    pythonProc = spawn(pythonCommand, ['-m', 'backend.run'], {
      cwd: webAppDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env },
    })
  } else {
    // In packaged mode, spawn bundled binary (post-Phase 7)
    const backendExe = path.join(webAppDir, 'voice-diary-backend', 'backend.run')
    pythonProc = spawn(backendExe, [], {
      cwd: webAppDir,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  }

  const spawnError = new Promise<never>((_, reject) => {
    pythonProc?.once('error', (err) => {
      console.error('[python] failed to start', err)
      reject(err)
    })
  })

  pythonProc.stdout?.on('data', (d: Buffer) => console.log('[python]', d.toString().trim()))
  pythonProc.stderr?.on('data', (d: Buffer) => console.error('[python]', d.toString().trim()))
  pythonProc.on('exit', (code) => console.log('[python] exited with', code))

  await Promise.race([waitUntilReady(MAX_ATTEMPTS), spawnError])
}

export function stopPythonBackend(): void {
  if (pythonProc) {
    pythonProc.kill('SIGTERM')
    pythonProc = null
  }
}
