import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AudioWebSocket, downsampleTo16k } from './websocket'

type WsHandler = ((event?: { data?: string }) => void) | null

class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static instances: MockWebSocket[] = []

  onopen: WsHandler = null
  onmessage: WsHandler = null
  onerror: WsHandler = null
  onclose: WsHandler = null
  readyState = MockWebSocket.CONNECTING
  sent: Array<string | ArrayBuffer> = []
  readonly url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data)
  }

  open() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  receive(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

describe('AudioWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('sends a start frame for the selected track and resolves only after started', async () => {
    const socket = new AudioWebSocket('system')
    const opened = vi.fn()
    socket.on('open', opened)

    const connected = socket.connect('session-1')
    const ws = MockWebSocket.instances[0]

    expect(ws.url).toContain('/ws/audio?track=system')
    ws.open()
    expect(ws.sent).toEqual([JSON.stringify({ type: 'start', session_id: 'session-1' })])

    ws.receive({ type: 'started' })

    await expect(connected).resolves.toBeUndefined()
    expect(opened).toHaveBeenCalledOnce()
  })

  it('rejects startup when backend sends an error frame before started', async () => {
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    socket.on('error', (err) => errors.push(err as Error))

    const connected = socket.connect('session-2')
    const ws = MockWebSocket.instances[0]

    ws.open()
    ws.receive({ type: 'error', message: 'model failed to load' })

    await expect(connected).rejects.toThrow('model failed to load')
    expect(errors).toHaveLength(1)
    expect(errors[0].message).toBe('model failed to load')
  })

  it('emits utterance frames after the connection is established', async () => {
    const socket = new AudioWebSocket()
    const utterances: unknown[] = []
    socket.on('utterance', (data) => utterances.push(data))

    const connected = socket.connect('session-3')
    const ws = MockWebSocket.instances[0]
    ws.open()
    ws.receive({ type: 'started' })
    await connected

    ws.receive({ type: 'utterance', data: { id: 'utt-1', transcript: 'hello' } })

    expect(utterances).toEqual([{ id: 'utt-1', transcript: 'hello' }])
  })

  it('does not send PCM chunks after stop clears the underlying socket', () => {
    const socket = new AudioWebSocket()
    void socket.connect('session-4')
    const ws = MockWebSocket.instances[0]
    ws.open()
    ws.receive({ type: 'started' })

    const chunk = new ArrayBuffer(4)
    socket.stop()
    socket.sendPCMChunk(chunk)

    expect(ws.sent).toEqual([
      JSON.stringify({ type: 'start', session_id: 'session-4' }),
      JSON.stringify({ type: 'stop' }),
    ])
  })

  it('closes and rejects when the startup handshake times out', async () => {
    vi.useFakeTimers()
    const socket = new AudioWebSocket()
    const errors: Error[] = []
    socket.on('error', (err) => errors.push(err as Error))

    const connected = socket.connect('session-5')
    const ws = MockWebSocket.instances[0]

    vi.advanceTimersByTime(10_000)

    await expect(connected).rejects.toThrow()
    expect(ws.readyState).toBe(MockWebSocket.CLOSED)
    expect(errors).toHaveLength(1)
  })
})

describe('downsampleTo16k', () => {
  it('returns the same buffer when audio is already 16 kHz', () => {
    const input = new Float32Array([0.1, 0.2, 0.3])

    expect(downsampleTo16k(input, 16000)).toBe(input)
  })

  it('samples at the source-rate ratio when converting to 16 kHz', () => {
    const input = new Float32Array([0, 1, 2, 3, 4, 5, 6, 7])

    expect(Array.from(downsampleTo16k(input, 32000))).toEqual([0, 2, 4, 6])
  })

  it('uses floored source indexes for non-integer source-rate ratios', () => {
    const input = new Float32Array([0, 1, 2, 3, 4, 5, 6, 7, 8])

    expect(Array.from(downsampleTo16k(input, 44100))).toEqual([0, 2, 5])
  })
})
