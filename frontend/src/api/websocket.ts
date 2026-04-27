import i18n from '../i18n'
import { WS_URL } from './client'

type EventType = 'utterance' | 'speaker_segment' | 'error' | 'open' | 'close'
type Handler = (data: unknown) => void
type ServerMessage = {
  type?: string
  data?: unknown
  message?: string
  session_id?: string
}

const WS_CONNECT_TIMEOUT_MS = 10_000

function wsUnavailable(): string {
  return i18n.t('api.wsUnavailable')
}

function messageError(msg: ServerMessage): Error {
  const detail =
    typeof msg.message === 'string'
      ? msg.message
      : typeof msg.data === 'string'
        ? msg.data
        : i18n.t('api.wsUnknownError')
  return new Error(detail)
}

export type AudioTrack = 'mic' | 'system'

export class AudioWebSocket {
  private ws: WebSocket | null = null
  private handlers = new Map<EventType, Set<Handler>>()
  readonly track: AudioTrack

  constructor(track: AudioTrack = 'mic') {
    this.track = track
  }

  on(type: EventType, h: Handler): () => void {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set())
    this.handlers.get(type)!.add(h)
    return () => this.handlers.get(type)?.delete(h)
  }

  private emit(type: EventType, data: unknown) {
    this.handlers.get(type)?.forEach((h) => h(data))
  }

  connect(sessionId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`${WS_URL}/ws/audio?track=${this.track}`)
      this.ws = ws
      let settled = false
      const timeout = window.setTimeout(() => {
        if (settled) return
        settled = true
        ws.close()
        const err = new Error(`${wsUnavailable()} ${i18n.t('api.sessionStartTimeout')}`)
        this.emit('error', err)
        reject(err)
      }, WS_CONNECT_TIMEOUT_MS)

      const finish = (err?: Error) => {
        if (settled) return
        settled = true
        window.clearTimeout(timeout)
        if (err) {
          this.emit('error', err)
          reject(err)
        } else {
          this.emit('open', null)
          resolve()
        }
      }

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'start', session_id: sessionId }))
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string) as ServerMessage
          if (msg.type === 'started') {
            finish()
            return
          }
          if (msg.type === 'error') {
            const err = messageError(msg)
            if (settled) this.emit('error', err)
            else finish(err)
            return
          }
          if (
            msg.type === 'utterance' ||
            msg.type === 'speaker_segment' ||
            msg.type === 'close'
          ) {
            this.emit(msg.type, msg.data)
          }
        } catch {
          /* ignore malformed frames */
        }
      }

      ws.onerror = () => {
        finish(new Error(wsUnavailable()))
      }

      ws.onclose = () => {
        if (!settled) finish(new Error(`${wsUnavailable()} ${i18n.t('api.sessionConnectionClosed')}`))
        this.emit('close', null)
      }
    })
  }

  sendPCMChunk(buffer: ArrayBuffer) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(buffer)
  }

  stop() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'stop' }))
      this.ws.close()
    }
    this.ws = null
  }
}

/** Linear downsample Float32Array from srcRate to 16000 Hz (simple decimation). */
export function downsampleTo16k(buf: Float32Array, srcRate: number): Float32Array {
  if (srcRate === 16000) return buf
  const ratio = srcRate / 16000
  const outLen = Math.floor(buf.length / ratio)
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) out[i] = buf[Math.floor(i * ratio)]
  return out
}
