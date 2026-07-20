import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AudioWebSocket } from './websocket'

class LifecycleWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  readyState = LifecycleWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  sent: Array<string | ArrayBuffer> = []
  close = vi.fn(() => { this.readyState = 3; this.onclose?.() })
  constructor(readonly url: string) { instances.push(this) }
  send(data: string | ArrayBuffer) { this.sent.push(data) }
  open() { this.readyState = LifecycleWebSocket.OPEN; this.onopen?.() }
  receive(message: unknown) { this.onmessage?.({ data: JSON.stringify(message) }) }
  receiveRaw(data: string) { this.onmessage?.({ data }) }
  fail() { this.onerror?.() }
}
const instances: LifecycleWebSocket[] = []

describe('AudioWebSocket lifecycle', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { instances.length = 0; vi.unstubAllGlobals(); vi.useRealTimers() })

  it('transitions CONNECTING to OPEN, sends the start frame, and resolves on started', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket('system')
    const opened = vi.fn()
    socket.on('open', opened)

    const connection = socket.connect('session-1')
    const ws = instances[0]
    expect(ws.readyState).toBe(LifecycleWebSocket.CONNECTING)
    ws.open()
    expect(ws.readyState).toBe(LifecycleWebSocket.OPEN)
    expect(ws.sent).toEqual([JSON.stringify({ type: 'start', session_id: 'session-1' })])
    ws.receive({ type: 'started' })

    await connection
    expect(opened).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects and emits one error when the socket errors before the handshake', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    const closes: unknown[] = []
    socket.on('error', (error) => errors.push(error as Error))
    socket.on('close', (data) => closes.push(data))

    const connection = socket.connect('pre-error')
    const rejection = expect(connection).rejects.toThrow(/WebSocket|з'єднання/i)
    const ws = instances[0]
    ws.open()
    ws.fail()
    ws.close()

    await rejection
    expect(errors).toHaveLength(1)
    expect(closes).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects with the startup-close error when CLOSED arrives before started', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    const closes: unknown[] = []
    socket.on('error', (error) => errors.push(error as Error))
    socket.on('close', (data) => closes.push(data))

    const connection = socket.connect('pre-close')
    const rejection = expect(connection).rejects.toThrow(/before session start|до старту/i)
    const ws = instances[0]
    ws.open()
    ws.close()

    await rejection
    expect(errors).toHaveLength(1)
    expect(closes).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects on a pre-handshake server error and ignores malformed frames', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    socket.on('error', (error) => errors.push(error as Error))

    const connection = socket.connect('pre-server-error')
    const rejection = expect(connection).rejects.toThrow('server rejected session')
    const ws = instances[0]
    ws.open()
    ws.receiveRaw('{not-json')
    expect(errors).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(1)

    ws.receive({ type: 'error', message: 'server rejected session' })

    await rejection
    expect(errors).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('closes and rejects once when the startup handshake times out', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    const closes: unknown[] = []
    socket.on('error', (error) => errors.push(error as Error))
    socket.on('close', (data) => closes.push(data))

    const connection = socket.connect('timeout')
    const rejection = expect(connection).rejects.toThrow(/timeout|очікування/i)
    const ws = instances[0]
    await vi.advanceTimersByTimeAsync(10_000)

    await rejection
    expect(ws.readyState).toBe(LifecycleWebSocket.CLOSED)
    expect(ws.close).toHaveBeenCalledOnce()
    expect(errors).toHaveLength(1)
    expect(closes).toHaveLength(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not double-settle when terminal server-error, error, and close events race', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    const closes: unknown[] = []
    socket.on('error', (error) => errors.push(error as Error))
    socket.on('close', (data) => closes.push(data))

    const connection = socket.connect('duplicate-terminal')
    const rejection = expect(connection).rejects.toThrow('first terminal error')
    const ws = instances[0]
    ws.open()
    ws.receive({ type: 'error', message: 'first terminal error' })
    ws.fail()
    ws.close()

    await rejection
    expect(errors.map((error) => error.message)).toEqual(['first terminal error'])
    expect(closes).toHaveLength(1)
  })

  it('emits post-handshake server errors without rejecting the established connection', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket('system')
    const errors: Error[] = []
    const closes: unknown[] = []
    socket.on('error', (error) => errors.push(error as Error))
    socket.on('close', (data) => closes.push(data))

    const connection = socket.connect('established')
    const ws = instances[0]
    ws.open()
    ws.receive({ type: 'started' })
    await connection

    ws.receive({ type: 'error', message: 'pipeline failed' })
    ws.close()

    expect(errors.map((error) => error.message)).toEqual(['pipeline failed'])
    expect(closes).toHaveLength(1)
  })

  it('stops an open socket, detaches handlers, and ignores late frames', async () => {
    vi.stubGlobal('WebSocket', LifecycleWebSocket)
    const socket = new AudioWebSocket()
    const utterances: unknown[] = []
    const errors: unknown[] = []
    socket.on('utterance', (data) => utterances.push(data))
    socket.on('error', (data) => errors.push(data))
    const connection = socket.connect('session-2')
    const ws = instances[0]
    ws.open()
    ws.receive({ type: 'started' })
    await connection

    socket.stop()
    expect(ws.sent).toContain(JSON.stringify({ type: 'stop' }))
    expect(ws.close).not.toHaveBeenCalled()
    expect(ws.onmessage).toBeNull()
    expect(ws.onopen).toBeNull()
    expect(ws.onerror).toBeNull()
    expect(ws.onclose).toBeNull()

    ws.receive({ type: 'utterance', data: { id: 'late' } })
    ws.receive({ type: 'error', message: 'late error' })
    ws.close()
    socket.sendPCMChunk(new ArrayBuffer(2))

    expect(utterances).toEqual([])
    expect(errors).toEqual([])
    expect(ws.sent).toEqual([
      JSON.stringify({ type: 'start', session_id: 'session-2' }),
      JSON.stringify({ type: 'stop' }),
    ])
  })
})
