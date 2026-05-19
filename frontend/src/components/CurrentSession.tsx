import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../query/keys'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { useVirtualizer } from '@tanstack/react-virtual'
import { AudioWebSocket, downsampleTo16k } from '../api/websocket'
import {
  getSystemAudioStream,
  isSystemAudioSupported,
  SystemAudioUnavailableError,
} from '../api/system-audio'
import { createSession } from '../api/sessions'
import { useContactsData } from '../query/contacts'
import type { Utterance } from '../types/domain'
import { fmt } from '../utils/format'

/** Merge granular (live-streamed) utterances from the same speaker when
 *  the gap between them is under 1 second.  Keeps the display clean during
 *  fast exchanges while backend embeddings are still extracted from the
 *  accumulated audio when the speaker's turn ends. */
const MERGE_GAP_MS = 1000

function mergeLiveUtterance(prev: Utterance[], next: Utterance): Utterance[] {
  if (prev.length === 0) return [next]
  const last = prev[prev.length - 1]
  const gap = (next.startedMs ?? 0) - (last.endedMs ?? 0)
  if (
    last.speakerId === next.speakerId &&
    last.source === next.source &&
    gap >= 0 && gap < MERGE_GAP_MS
  ) {
    const merged: Utterance = {
      ...last,
      id: next.id,
      speakerSegmentId: next.speakerSegmentId ?? last.speakerSegmentId,
      text: last.text + ' ' + next.text,
      endedMs: next.endedMs,
    }
    return [...prev.slice(0, -1), merged]
  }
  return [...prev, next]
}

import { Avatar } from './shared/Avatar'
import { AudioLevelFooterLive } from './shared/AudioLevelFooter'
import { useDeleteUtteranceMutation } from '../query/sessions'
import { useToast } from './Toast/useToast'

type RecState = 'idle' | 'starting' | 'recording' | 'paused'

interface UtteranceRowProps {
  utt: Utterance
  isLive?: boolean
  isDraft?: boolean
  onDelete?: (utteranceId: string) => void
  deleting?: boolean
}

const UtteranceRow = memo(function UtteranceRow({
  utt,
  isLive = false,
  isDraft = false,
  onDelete,
  deleting = false,
}: UtteranceRowProps) {
  const { t } = useTranslation()
  const { contactById } = useContactsData()
  const contact = contactById(utt.speakerId)
  const sourceLabel = utt.source === 'system' ? 'SYS' : utt.source === 'mic' ? 'MIC' : null
  const displayName = contact ? contact.name : utt.source === 'mic' ? t('common.you') : t('common.unknown')

  return (
    <>
    <div data-testid={`utterance-${utt.id}`} style={{ ...csS.uttRow, padding: 'var(--utt-padding, 13px 0)' }}>
      <Avatar contact={contact} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={csS.uttMeta}>
          <span style={{ ...csS.uttName, color: contact ? contact.color : 'var(--text-muted)', fontStyle: contact ? 'normal' : 'italic' }}>
            {displayName}
          </span>
          <span style={csS.uttTime}>{utt.time}</span>
          {sourceLabel && (
            <span
              title={
                utt.source === 'system'
                  ? t('currentSession.sourceSystem')
                  : t('currentSession.sourceMic')
              }
              style={csS.sourceTag}
            >
              {sourceLabel}
            </span>
          )}
          {utt.lang && <span style={csS.langTag}>{utt.lang}</span>}
          {!isLive && !isDraft && onDelete && (
            <button
              data-testid={`delete-utt-${utt.id}`}
              onClick={(e) => { e.stopPropagation(); onDelete(utt.id!) }}
              disabled={deleting}
              style={{
                ...csS.deleteBtn,
                opacity: deleting ? 0.15 : 0.3,
                cursor: deleting ? 'default' : 'pointer',
              }}
            >
              ✕
            </button>
          )}
        </div>
        <div style={{ ...csS.uttText, color: contact ? 'var(--text)' : isDraft ? 'var(--text-dim)' : 'var(--text-soft)', fontFamily: 'var(--utterance-font, var(--sans))', fontStyle: isDraft ? 'italic' : 'normal' }}>
          {isLive ? (
            <span style={{ display: 'flex', gap: 3, alignItems: 'center', height: 18 }}>
              {[0, 1, 2].map((i) => (
                <span key={i} style={{
                  width: 4, height: 4, borderRadius: '50%', background: 'var(--text-dim)',
                  display: 'inline-block', animation: `blink 1.2s ${i * 0.2}s ease-in-out infinite`,
                }} />
              ))}
            </span>
          ) : utt.text}
        </div>
      </div>
    </div>
    </>
  )
})

interface CurrentSessionProps {
  setRecording: (r: boolean) => void
  utterances: Utterance[]
  setUtterances: (updater: (prev: Utterance[]) => Utterance[]) => void
  onSessionIdChange?: (sessionId: string | null) => void
  onIdentifyUnknown?: () => void
}

interface SpeakerStat {
  speakerId: string | null
  ms: number
  order: number
}

interface AudioLevelSnapshot {
  db: number
  level: number
}

const SILENCE_SNAPSHOT: AudioLevelSnapshot = { db: -60, level: 0 }
const ESTIMATE_SIZE = () => 120

function measureAudioLevel(samples: Float32Array): AudioLevelSnapshot {
  if (samples.length === 0) return SILENCE_SNAPSHOT
  let sum = 0
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
  const rms = Math.sqrt(sum / samples.length)
  if (!Number.isFinite(rms) || rms <= 1e-4) return SILENCE_SNAPSHOT
  const db = Math.max(-60, Math.min(0, 20 * Math.log10(rms)))
  return { db, level: (db + 60) / 60 }
}

function recordingErrorMessage(err: unknown, t: (k: string) => string): string {
  if (!(err instanceof Error)) return t('currentSession.errorRecord')
  if (err.name === 'NotAllowedError') return t('currentSession.errorMicDenied')
  if (err.name === 'NotFoundError') return t('currentSession.errorMicNotFound')
  if (err.name === 'NotReadableError') return t('currentSession.errorMicBusy')
  return err.message || t('currentSession.errorRecord')
}

export function CurrentSession({
  setRecording,
  utterances,
  setUtterances,
  onSessionIdChange,
  onIdentifyUnknown,
}: CurrentSessionProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { contactById } = useContactsData()
  const [recState, setRecState] = useState<RecState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [showLive, setShowLive] = useState(false)
  const [draftText, setDraftText] = useState<string | null>(null)
  const { addToast } = useToast()
  const micLevelRef = useRef<AudioLevelSnapshot>(SILENCE_SNAPSHOT)
  const sysLevelRef = useRef<AudioLevelSnapshot>(SILENCE_SNAPSHOT)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const timerRef = useRef<number | null>(null)
  const wsRef = useRef<AudioWebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  // Parallel chain for system-audio loopback. Kept in its own AudioContext
  // so the mic and system streams stay independent — they have separate VAD
  // and ASR pipelines on the server, and any cross-talk in audio plumbing
  // would defeat the point.
  const sysWsRef = useRef<AudioWebSocket | null>(null)
  const sysCtxRef = useRef<AudioContext | null>(null)
  const sysSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const sysProcessorRef = useRef<ScriptProcessorNode | null>(null)
  const sysStreamRef = useRef<MediaStream | null>(null)
  const [systemEnabled, setSystemEnabled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage?.getItem('vd_capture_system') === '1'
  })
  const systemSupported = isSystemAudioSupported()

  const deleteMutation = useDeleteUtteranceMutation(sessionId)
  const deletingRef = useRef<Set<string>>(new Set())
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const onDeleteUtterance = useCallback(
    async (uttId: string) => {
      if (deletingRef.current.has(uttId)) return
      deletingRef.current.add(uttId)
      setDeletingIds(new Set(deletingRef.current))
      try {
        await deleteMutation.mutateAsync(uttId)
      } finally {
        deletingRef.current.delete(uttId)
        setDeletingIds(new Set(deletingRef.current))
      }
    },
    [deleteMutation],
  )

  // ---- virtualized utterance list ------------------------------------

  const rowVirtualizer = useVirtualizer({
    count: utterances.length,
    getScrollElement: useCallback(() => transcriptRef.current, []),
    estimateSize: ESTIMATE_SIZE,
    overscan: 3,
  })

  // ---- memoized stats (avoids O(n) compute on audio-level re-renders) --

  const { speakerStats, totalMs, unknownInSession } = useMemo(() => {
    const stats = utterances.reduce<Record<string, SpeakerStat>>((acc, u, idx) => {
      const k = u.speakerId ?? '__unk__'
      if (!acc[k]) acc[k] = { speakerId: u.speakerId, ms: 0, order: idx }
      acc[k].ms += 4500
      return acc
    }, {})
    const total = Object.values(stats).reduce((s, v) => s + v.ms, 0) || 1
    const unknown = utterances.filter(
      (u) => !u.speakerId && u.speakerSegmentId !== undefined,
    ).length
    return { speakerStats: stats, totalMs: total, unknownInSession: unknown }
  }, [utterances])

  useEffect(() => {
    if (recState === 'recording') {
      timerRef.current = window.setInterval(() => setElapsed((e) => e + 1), 1000)
    } else if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current !== null) window.clearInterval(timerRef.current) }
  }, [recState])

  useEffect(() => {
    if (showLive && transcriptRef.current) {
      rowVirtualizer.measure()
      rowVirtualizer.scrollToIndex(utterances.length - 1, { align: 'end' })
    }
  }, [utterances, showLive, rowVirtualizer])

  const stopAudio = () => {
    micLevelRef.current = SILENCE_SNAPSHOT
    sysLevelRef.current = SILENCE_SNAPSHOT
    if (processorRef.current) processorRef.current.onaudioprocess = null
    try {
      processorRef.current?.disconnect()
    } catch {
      /* already disconnected */
    }
    try {
      sourceRef.current?.disconnect()
    } catch {
      /* already disconnected */
    }
    audioCtxRef.current?.close().catch(() => undefined)
    streamRef.current?.getTracks().forEach((t) => t.stop())
    processorRef.current = null
    sourceRef.current = null
    audioCtxRef.current = null
    streamRef.current = null

    if (sysProcessorRef.current) sysProcessorRef.current.onaudioprocess = null
    try {
      sysProcessorRef.current?.disconnect()
    } catch {
      /* already disconnected */
    }
    try {
      sysSourceRef.current?.disconnect()
    } catch {
      /* already disconnected */
    }
    sysCtxRef.current?.close().catch(() => undefined)
    sysStreamRef.current?.getTracks().forEach((t) => t.stop())
    sysProcessorRef.current = null
    sysSourceRef.current = null
    sysCtxRef.current = null
    sysStreamRef.current = null
  }

  const startSystemCapture = async (sessionId: string) => {
    const stream = await getSystemAudioStream()
    sysStreamRef.current = stream

    const sysWs = new AudioWebSocket('system')
    sysWsRef.current = sysWs
    sysWs.on('utterance', (data) => {
      const d = data as {
        id: string
        transcript: string
        started_ms: number
        ended_ms: number
        language: string | null
        speaker_segment_id: string | null
        speaker_contact_id: string | null
        source?: string
      }
      const s = Math.floor(d.started_ms / 1000)
      const m = Math.floor(s / 60)
      const time = `${m}:${String(s % 60).padStart(2, '0')}`
      setUtterances((prev) =>
        mergeLiveUtterance(prev, {
          id: d.id,
          speakerId: d.speaker_contact_id,
          speakerSegmentId: d.speaker_segment_id,
          time,
          text: d.transcript,
          lang: d.language === 'EN' ? 'EN' : d.language === 'UK' ? 'UK' : undefined,
          source: 'system',
          startedMs: d.started_ms,
          endedMs: d.ended_ms,
        }),
      )
    })

    sysWs.on('draft_utterance', (data) => {
      const d = data as { transcript: string }
      setDraftText(d.transcript)
    })

    sysWs.on('error', (err) => addToast({
      type: 'error',
      title: 'System Audio Error',
      message: recordingErrorMessage(err, t),
    }))

    sysWs.on('speaker_segment', (data) => {
      const d = data as { id: string; contact_id: string | null; status: string }
      if (d.contact_id && d.status === 'identified') {
        setUtterances((prev) =>
          prev.map((u) =>
            u.speakerSegmentId === d.id ? { ...u, speakerId: d.contact_id } : u,
          ),
        )
      }
    })

    await sysWs.connect(sessionId)

    const ctx = new AudioContext({ sampleRate: 16000 })
    sysCtxRef.current = ctx
    const actualRate = ctx.sampleRate
    const src = ctx.createMediaStreamSource(stream)
    sysSourceRef.current = src
    const processor = ctx.createScriptProcessor(4096, 1, 1)
    sysProcessorRef.current = processor
    processor.onaudioprocess = (e) => {
      const f32 = e.inputBuffer.getChannelData(0)
      sysLevelRef.current = measureAudioLevel(f32)
      const chunk = actualRate === 16000 ? f32 : downsampleTo16k(f32, actualRate)
      sysWs.sendPCMChunk(chunk.buffer as ArrayBuffer)
    }
    src.connect(processor)
    processor.connect(ctx.destination)
  }

  const start = async () => {
    if (recState !== 'idle') return

    setRecState('starting')
    setRecording(false)
    setShowLive(false)
    setElapsed(0)

    try {
      setUtterances(() => [])
      const session = await createSession('', undefined)
      setSessionId(session.id)
      onSessionIdChange?.(session.id)
      const ws = new AudioWebSocket()
      wsRef.current = ws

      ws.on('utterance', (data) => {
        const d = data as {
          id: string
          transcript: string
          started_ms: number
          ended_ms: number
          language: string | null
          speaker_segment_id: string | null
          speaker_contact_id: string | null
          source?: string
        }
        const s = Math.floor(d.started_ms / 1000)
        const m = Math.floor(s / 60)
        const time = `${m}:${String(s % 60).padStart(2, '0')}`
        setShowLive(false)
        setDraftText(null)
        setUtterances((prev) =>
          mergeLiveUtterance(prev, {
            id: d.id,
            speakerId: d.speaker_contact_id,
            speakerSegmentId: d.speaker_segment_id,
            time,
            text: d.transcript,
            lang: d.language === 'EN' ? 'EN' : d.language === 'UK' ? 'UK' : undefined,
            source: 'mic',
            startedMs: d.started_ms,
            endedMs: d.ended_ms,
          }),
        )
      })

      ws.on('draft_utterance', (data) => {
        const d = data as { transcript: string }
        setDraftText(d.transcript)
      })

      ws.on('error', (err) => addToast({
        type: 'error',
        title: 'Pipeline Error',
        message: recordingErrorMessage(err, t),
      }))

      ws.on('speaker_segment', (data) => {
        const d = data as { id: string; contact_id: string | null; status: string }
        if (d.contact_id && d.status === 'identified') {
          setUtterances((prev) =>
            prev.map((u) =>
              u.speakerSegmentId === d.id ? { ...u, speakerId: d.contact_id } : u,
            ),
          )
        }
      })

      const streamPromise = navigator.mediaDevices?.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
      })

      await ws.connect(session.id)

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(t('currentSession.errorBrowserUnsupported'))
      }

      const stream = await streamPromise
      streamRef.current = stream

      const ctx = new AudioContext({ sampleRate: 16000 })
      audioCtxRef.current = ctx
      const actualRate = ctx.sampleRate

      const src = ctx.createMediaStreamSource(stream)
      sourceRef.current = src
      const processor = ctx.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        const f32 = e.inputBuffer.getChannelData(0)
        micLevelRef.current = measureAudioLevel(f32)
        const chunk = actualRate === 16000 ? f32 : downsampleTo16k(f32, actualRate)
        ws.sendPCMChunk(chunk.buffer as ArrayBuffer)
      }

      src.connect(processor)
      processor.connect(ctx.destination)

      if (systemEnabled && systemSupported) {
        try {
          await startSystemCapture(session.id)
        } catch (sysErr) {
          // System capture is opt-in: don't block the mic recording, just
          // surface a non-fatal warning.
          const msg =
            sysErr instanceof SystemAudioUnavailableError
              ? sysErr.message
              : recordingErrorMessage(sysErr, t)
          addToast({ type: 'error', title: 'System Audio Error', message: msg })
        }
      }

      setRecState('recording')
      setRecording(true)
      setShowLive(true)
    } catch (err) {
      wsRef.current?.stop()
      wsRef.current = null
      sysWsRef.current?.stop()
      sysWsRef.current = null
      stopAudio()
      setRecState('idle')
      setRecording(false)
      setShowLive(false)
      onSessionIdChange?.(null)
      addToast({ type: 'error', title: 'Recording Error', message: recordingErrorMessage(err, t) })
    }
  }

  const pause = () => {
    processorRef.current?.disconnect()
    sourceRef.current?.disconnect()
    micLevelRef.current = SILENCE_SNAPSHOT
    sysLevelRef.current = SILENCE_SNAPSHOT
    setRecState('paused')
    setRecording(false)
    setShowLive(false)
  }

  const resume = () => {
    if (sourceRef.current && processorRef.current && audioCtxRef.current) {
      sourceRef.current.connect(processorRef.current)
      processorRef.current.connect(audioCtxRef.current.destination)
    }
    setRecState('recording')
    setRecording(true)
    setShowLive(true)
  }

  const stop = () => {
    wsRef.current?.stop()
    wsRef.current = null
    sysWsRef.current?.stop()
    sysWsRef.current = null
    stopAudio()
    setRecState('idle')
    setRecording(false)
    setElapsed(0)
    setShowLive(false)
    onSessionIdChange?.(null)
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions.list() })
  }

  useEffect(() => () => {
    wsRef.current?.stop()
    sysWsRef.current?.stop()
    stopAudio()
    onSessionIdChange?.(null)
    setRecording(false)
  }, [onSessionIdChange, setRecording])

  const toggleSystemCapture = (next: boolean) => {
    setSystemEnabled(next)
    try {
      window.localStorage?.setItem('vd_capture_system', next ? '1' : '0')
    } catch {
      /* localStorage may be disabled — non-fatal */
    }
  }

  return (
    <div style={csS.root}>
      <div style={csS.topbar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {recState !== 'idle' ? (
            <span style={csS.recPill}>
              <span
                data-testid="rec-dot"
                className={recState === 'recording' ? 'rec-pulse' : ''}
                style={{ ...csS.recDot, background: recState === 'recording' ? 'var(--record)' : 'var(--text-dim)' }}
              />
              <span style={csS.recPillLabel}>
                {recState === 'starting'
                  ? t('currentSession.starting')
                  : recState === 'paused'
                    ? t('currentSession.btnPause')
                    : t('currentSession.title')}
              </span>
              <span style={csS.recPillSep} />
              <span style={csS.timerText}>
                {recState === 'starting' ? '0:00' : fmt(elapsed)}
              </span>
            </span>
          ) : (
            <span style={csS.screenTitle}>{t('currentSession.title')}</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {systemSupported && recState === 'idle' && (
            <label data-testid="system-audio-toggle" style={csS.systemToggle} title={t('currentSession.captureSystemHint')}>
              <input
                type="checkbox"
                checked={systemEnabled}
                onChange={(e) => toggleSystemCapture(e.target.checked)}
                style={{ accentColor: 'var(--accent)' }}
              />
              <span>{t('currentSession.captureSystem')}</span>
            </label>
          )}
          {recState === 'recording' && systemEnabled && systemSupported && (
            <span style={csS.systemActive} title={t('currentSession.captureSystem')}>
              SYS · {t('currentSession.captureSystem')}
            </span>
          )}
          {recState === 'idle' && (
            <button onClick={() => void start()} data-testid="btn-start" style={csS.btnPrimary}>{t('currentSession.btnStart')}</button>
          )}
          {recState === 'starting' && (
            <button disabled style={{ ...csS.btnPrimary, opacity: 0.65, cursor: 'wait' }}>{t('currentSession.btnStarting')}</button>
          )}
          {recState === 'recording' && (
            <>
              <button onClick={pause} data-testid="btn-pause" style={csS.btnSecondary}>{t('currentSession.btnPause')}</button>
              <button onClick={stop} data-testid="btn-stop" style={csS.btnDanger}>{t('currentSession.btnStop')}</button>
            </>
          )}
          {recState === 'paused' && (
            <>
              <button onClick={resume} data-testid="btn-resume" style={csS.btnPrimary}>{t('currentSession.btnResume')}</button>
              <button onClick={stop} data-testid="btn-stop" style={csS.btnDanger}>{t('currentSession.btnStop')}</button>
            </>
          )}
        </div>
      </div>

      <div style={csS.body}>
        <div style={csS.transcript} ref={transcriptRef}>
          {utterances.length === 0 && recState === 'idle' && (
            <div style={csS.emptyState}>
              <div style={csS.emptyIcon}>◎</div>
              <div style={csS.emptyTitle}>{t('currentSession.emptyTitle')}</div>
              <div style={csS.emptySub}>{t('currentSession.emptySub')}</div>
            </div>
          )}
          <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', flexShrink: 0 }}>
            {rowVirtualizer.getVirtualItems().map((v) => {
              const u = utterances[v.index]
              return (
                <div
                  key={v.key}
                  data-index={v.index}
                  ref={rowVirtualizer.measureElement}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${v.start}px)` }}
                >
                  <UtteranceRow
                    utt={u}
                    onDelete={onDeleteUtterance}
                    deleting={deletingIds.has(u.id!)}
                  />
                </div>
              )
            })}
          </div>
          {showLive && (
            <UtteranceRow
              utt={{
                id: 'live',
                speakerId: null,
                time: fmt(elapsed),
                text: draftText ?? '',
              }}
              isLive={!draftText}
              isDraft={!!draftText}
            />
          )}
        </div>

        <div style={csS.sidePane}>
          <div data-testid="speaker-sidebar" style={csS.sideBlock}>
            <div style={csS.sideTitle}>{t('currentSession.speakers')}</div>
            {Object.values(speakerStats)
              .sort((a, b) => a.order - b.order)
              .map((s) => {
                const c = contactById(s.speakerId)
                const pct = Math.round((s.ms / totalMs) * 100)
                return (
                  <div key={s.speakerId ?? 'unk'} style={csS.speakerRow}>
                    <Avatar contact={c} size={24} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 12, color: c ? c.color : 'var(--text-dim)', fontWeight: 500 }}>
                          {c ? c.name.split(' ')[0] : t('common.unknown')}
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>
                          {t('currentSession.secondsShort', { n: Math.round(s.ms / 1000) })}
                        </span>
                      </div>
                      <div style={csS.barBg}>
                        <div style={{ ...csS.barFill, width: `${pct}%`, background: c ? `${c.color}99` : 'rgba(38,37,30,0.2)' }} />
                      </div>
                    </div>
                  </div>
                )
              })}
            {utterances.length === 0 && (
              <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>{t('currentSession.noSpeakers')}</div>
            )}
          </div>

          {unknownInSession > 0 && (
            <div data-testid="unknown-speaker-section" style={{ ...csS.sideBlock, borderColor: 'rgba(207,45,86,0.25)' }}>
              <div style={csS.sideTitle}>{t('currentSession.unknownSpeakerCard')}</div>
              <div style={{ fontSize: 12, color: 'var(--record)', fontFamily: 'var(--mono)', marginBottom: 8 }}>
                {t('currentSession.fragments', { count: unknownInSession })}
              </div>
              <button data-testid="identify-unknown-btn" onClick={onIdentifyUnknown} style={csS.btnIdentify}>
                {t('currentSession.identify')}
              </button>
            </div>
          )}
        </div>
      </div>

      <div style={csS.bottombar}>
        <AudioLevelFooterLive
          active={recState === 'recording'}
          paused={recState === 'paused'}
          systemEnabled={systemEnabled && systemSupported}
          micLevelRef={micLevelRef}
          systemLevelRef={sysLevelRef}
        />
      </div>
    </div>
  )
}

const csS: Record<string, CSSProperties> = {
  root: { display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg)', fontFamily: 'var(--sans)' },
  topbar: {
    height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0 24px', borderBottom: '1px solid var(--border)', flexShrink: 0, background: 'var(--surface)',
  },
  screenTitle: { fontSize: 14.5, fontWeight: 600, color: 'var(--text)', letterSpacing: '-0.01em' },
  recPill: {
    display: 'inline-flex', alignItems: 'center', gap: 10,
    padding: '6px 12px', borderRadius: 9999,
    background: 'var(--bg)', border: '1px solid var(--border)',
  },
  recPillLabel: {
    fontSize: 11, fontFamily: 'var(--mono)', textTransform: 'uppercase',
    letterSpacing: '0.08em', color: 'var(--text-muted)',
  },
  recPillSep: { width: 1, height: 12, background: 'var(--border)' },
  recDot: { width: 8, height: 8, borderRadius: '50%', display: 'inline-block', flexShrink: 0 },
  timerText: { fontSize: 13.5, fontWeight: 600, fontFamily: 'var(--mono)', color: 'var(--text)', letterSpacing: '0.04em' },
  btnPrimary: { background: 'var(--surface3)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 14px', fontSize: 13, fontWeight: 500 },
  btnSecondary: { background: 'var(--bg)', color: 'var(--text-muted)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 14px', fontSize: 13, fontWeight: 500 },
  btnDanger: { background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border-med)', borderRadius: 8, padding: '7px 14px', fontSize: 13, fontWeight: 500 },
  body: { flex: 1, display: 'flex', overflow: 'hidden' },
  transcript: { flex: 1, overflowY: 'auto', padding: '16px 24px', display: 'flex', flexDirection: 'column' },
  sidePane: {
    width: 232, borderLeft: '1px solid var(--border)', overflowY: 'auto', padding: '14px',
    display: 'flex', flexDirection: 'column', gap: 10, flexShrink: 0, background: 'var(--surface)',
  },
  sideBlock: { background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px' },
  sideTitle: { fontSize: 10.5, fontWeight: 600, color: 'var(--text-dim)', letterSpacing: '0.07em', marginBottom: 10, fontFamily: 'var(--mono)', textTransform: 'uppercase' },
  speakerRow: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 },
  barBg: { height: 3, background: 'var(--surface3)', borderRadius: 2, overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: 2, transition: 'width 0.4s' },
  btnIdentify: {
    width: '100%', background: 'var(--record-dim)', border: '1px solid rgba(207,45,86,0.2)',
    color: 'var(--record)', borderRadius: 6, padding: '6px 12px', fontSize: 12, fontWeight: 500,
  },
  uttRow: { display: 'flex', gap: 12, borderBottom: '1px solid var(--border)' },
  uttMeta: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 },
  uttName: { fontSize: 12.5, fontWeight: 600, letterSpacing: '-0.005em' },
  uttTime: { fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'var(--mono)' },
  langTag: { fontSize: 9.5, fontFamily: 'var(--mono)', fontWeight: 600, padding: '1px 5px', background: 'var(--surface2)', color: 'var(--accent)', borderRadius: 3, letterSpacing: '0.04em' },
  sourceTag: {
    fontSize: 9.5, fontFamily: 'var(--mono)', fontWeight: 600,
    padding: '1px 5px', borderRadius: 3, letterSpacing: '0.06em',
    color: 'var(--text-muted)', background: 'var(--surface2)',
    border: '1px solid var(--border)',
  },
  systemToggle: {
    display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
    color: 'var(--text-muted)', cursor: 'pointer', userSelect: 'none',
    padding: '5px 10px', border: '1px solid var(--border)', borderRadius: 8,
    background: 'var(--bg)',
  },
  systemActive: {
    fontSize: 10.5, fontFamily: 'var(--mono)', color: 'var(--text-muted)',
    padding: '3px 8px', border: '1px solid var(--border)',
    borderRadius: 9999, background: 'var(--bg)', letterSpacing: '0.04em',
  },
  uttText: { fontSize: 14, lineHeight: 1.6, textWrap: 'pretty' },
  emptyState: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, paddingTop: '18vh' },
  emptyIcon: { fontSize: 34, color: 'var(--text-dim)', opacity: 0.4 },
  emptyTitle: { fontSize: 15, fontWeight: 600, color: 'var(--text-muted)' },
  emptySub: { fontSize: 13, color: 'var(--text-dim)' },
  bottombar: { minHeight: 64, borderTop: '1px solid var(--border)', background: 'var(--surface)', display: 'flex', alignItems: 'center', padding: '10px 24px', flexShrink: 0 },
  deleteBtn: {
    fontSize: 12, background: 'none', border: 'none',
    color: 'var(--text-muted)', fontFamily: 'var(--mono)',
    padding: '1px 5px', transition: 'opacity 0.15s',
  },
}
