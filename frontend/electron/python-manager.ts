import { ChildProcess, spawn } from 'child_process'
import * as http from 'http'
import * as fs from 'fs'
import * as path from 'path'

const BACKEND_PORT = 8765
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`
const MAX_ATTEMPTS = 40
const INTERVAL_MS = 500
const RUNTIME_STATE_FILE = 'install-state.json'

let pythonProc: ChildProcess | null = null

type StartBackendOptions = {
  appVersion: string
  devWebAppDir: string
  userDataDir: string
}

type RuntimeInstallState = {
  appVersion?: string
  status?: string
}

function resolvePythonCommand(webAppDir: string): string {
  const candidates = [
    path.join(webAppDir, '.venv-ml', 'Scripts', 'python.exe'),
    path.join(webAppDir, '.venv', 'Scripts', 'python.exe'),
  ]

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }

  return 'python'
}

function resolveRuntimeRoot(userDataDir: string): string {
  return path.join(userDataDir, 'backend-runtime')
}

function resolveLogsDir(userDataDir: string): string {
  return path.join(userDataDir, 'logs')
}

function resolveRuntimePython(runtimeRoot: string): string {
  return process.platform === 'win32'
    ? path.join(runtimeRoot, 'venv', 'Scripts', 'python.exe')
    : path.join(runtimeRoot, 'venv', 'bin', 'python')
}

function readRuntimeState(runtimeRoot: string): RuntimeInstallState | null {
  const statePath = path.join(runtimeRoot, RUNTIME_STATE_FILE)
  if (!fs.existsSync(statePath)) return null

  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf8')) as RuntimeInstallState
  } catch {
    return null
  }
}

function runtimeNeedsBootstrap(runtimeRoot: string, appVersion: string): boolean {
  const pythonCommand = resolveRuntimePython(runtimeRoot)
  const state = readRuntimeState(runtimeRoot)
  return !fs.existsSync(pythonCommand) || state?.status !== 'ok' || state.appVersion !== appVersion
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

function appendLog(logPath: string, line: string): void {
  fs.appendFileSync(logPath, `${line}\n`, 'utf8')
}

function runProcess(command: string, args: string[], cwd: string, label: string, logPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(logPath), { recursive: true })
    appendLog(logPath, `[${new Date().toISOString()}] ${label}: ${command} ${args.join(' ')}`)

    const proc = spawn(command, args, {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env },
    })

    proc.stdout?.on('data', (d: Buffer) => {
      const text = d.toString().trim()
      console.log(`[${label}]`, text)
      appendLog(logPath, text)
    })
    proc.stderr?.on('data', (d: Buffer) => {
      const text = d.toString().trim()
      console.error(`[${label}]`, text)
      appendLog(logPath, text)
    })
    proc.on('error', (err) => {
      appendLog(logPath, `[${new Date().toISOString()}] ${label} failed to start: ${err.message}`)
      reject(err)
    })
    proc.on('exit', (code) => {
      if (code === 0) {
        appendLog(logPath, `[${new Date().toISOString()}] ${label} exited successfully`)
        resolve()
      } else {
        const message = `${label} exited with code ${code ?? 'unknown'}; see ${logPath}`
        appendLog(logPath, `[${new Date().toISOString()}] ${message}`)
        reject(new Error(message))
      }
    })
  })
}

async function bootstrapPackagedRuntime(
  resourcesDir: string,
  runtimeRoot: string,
  appVersion: string,
  logPath: string,
): Promise<void> {
  const scriptsDir = path.join(resourcesDir, 'scripts')
  const command = process.platform === 'win32' ? 'powershell.exe' : '/usr/bin/env'
  const scriptPath = process.platform === 'win32'
    ? path.join(scriptsDir, 'runtime-install.ps1')
    : path.join(scriptsDir, 'runtime-install.sh')
  const args = process.platform === 'win32'
    ? [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-SourceRoot',
        resourcesDir,
        '-RuntimeRoot',
        runtimeRoot,
        '-AppVersion',
        appVersion,
        '-LogPath',
        logPath,
      ]
    : [
        'bash',
        scriptPath,
        '--source-root',
        resourcesDir,
        '--runtime-root',
        runtimeRoot,
        '--app-version',
        appVersion,
        '--log-path',
        logPath,
      ]

  if (!fs.existsSync(scriptPath)) {
    throw new Error(`Runtime bootstrap script not found: ${scriptPath}`)
  }

  await runProcess(command, args, resourcesDir, 'runtime-install', logPath)
}

export async function startPythonBackend(options: StartBackendOptions): Promise<void> {
  // Check if backend is already running (e.g., started externally)
  if (await healthCheck()) return

  const isDev = process.env.NODE_ENV === 'development'
  const resourcesDir = process.resourcesPath
  let pythonCommand: string
  let backendCwd: string

  if (isDev) {
    backendCwd = options.devWebAppDir
    pythonCommand = resolvePythonCommand(options.devWebAppDir)
  } else {
    const runtimeRoot = resolveRuntimeRoot(options.userDataDir)
    const logPath = path.join(resolveLogsDir(options.userDataDir), 'runtime-install.log')
    if (runtimeNeedsBootstrap(runtimeRoot, options.appVersion)) {
      await bootstrapPackagedRuntime(resourcesDir, runtimeRoot, options.appVersion, logPath)
    }
    backendCwd = resourcesDir
    pythonCommand = resolveRuntimePython(runtimeRoot)
  }

  pythonProc = spawn(pythonCommand, ['-m', 'backend.run'], {
    cwd: backendCwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
  })

  pythonProc.stdout?.on('data', (d: Buffer) => console.log('[python]', d.toString().trim()))
  pythonProc.stderr?.on('data', (d: Buffer) => console.error('[python]', d.toString().trim()))
  pythonProc.on('exit', (code) => console.log('[python] exited with', code))

  await waitUntilReady(MAX_ATTEMPTS)
}

export function stopPythonBackend(): void {
  if (pythonProc) {
    pythonProc.kill('SIGTERM')
    pythonProc = null
  }
}
