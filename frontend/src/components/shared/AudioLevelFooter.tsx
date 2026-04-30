import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

interface AudioLevelSnapshot {
  db: number
  level: number
}

interface AudioLevelFooterProps {
  active: boolean
  paused: boolean
  mic: AudioLevelSnapshot
  system?: AudioLevelSnapshot
}

interface AudioLevelFooterLiveProps {
  active: boolean
  paused: boolean
  systemEnabled: boolean
  micLevelRef: { current: AudioLevelSnapshot }
  systemLevelRef: { current: AudioLevelSnapshot }
}

function channelStatus(
  active: boolean,
  paused: boolean,
  level: number,
  t: (key: string) => string,
): string {
  if (paused) return t('currentSession.footerPaused')
  if (!active) return t('currentSession.footerIdle')
  return level > 0.12
    ? t('currentSession.footerVoice')
    : t('currentSession.footerQuiet')
}

function ChannelMeter({
  label,
  active,
  paused,
  tone,
  snapshot,
}: {
  label: string
  active: boolean
  paused: boolean
  tone: string
  snapshot: AudioLevelSnapshot
}) {
  const { t } = useTranslation()
  const dbLabel = active || paused ? `${Math.round(snapshot.db)} dB` : '—'
  const fillWidth = `${Math.max(0, Math.min(100, snapshot.level * 100))}%`

  return (
    <div style={st.channel}>
      <div style={st.topline}>
        <span style={st.label}>{label}</span>
        <span style={st.status}>
          {channelStatus(active, paused, snapshot.level, t)}
        </span>
      </div>
      <div style={st.bottomline}>
        <div style={st.meterTrack}>
          <div
            style={{
              ...st.meterFill,
              width: fillWidth,
              background: tone,
              opacity: active ? 1 : paused ? 0.7 : 0.3,
            }}
          />
        </div>
        <span style={st.db}>{dbLabel}</span>
      </div>
    </div>
  )
}

export function AudioLevelFooter({
  active,
  paused,
  mic,
  system,
}: AudioLevelFooterProps) {
  const { t } = useTranslation()

  return (
    <div style={st.root}>
      <div style={st.title}>{t('currentSession.footerInput')}</div>
      <div style={st.channels}>
        <ChannelMeter
          label={t('currentSession.sourceMic')}
          active={active}
          paused={paused}
          tone="linear-gradient(90deg, #b58f2f 0%, #cf2d56 100%)"
          snapshot={mic}
        />
        {system && (
          <ChannelMeter
            label={t('currentSession.sourceSystem')}
            active={active}
            paused={paused}
            tone="linear-gradient(90deg, #4e7f68 0%, #6aa38a 100%)"
            snapshot={system}
          />
        )}
      </div>
    </div>
  )
}

export function AudioLevelFooterLive({
  active,
  paused,
  systemEnabled,
  micLevelRef,
  systemLevelRef,
}: AudioLevelFooterLiveProps) {
  const [mic, setMic] = useState<AudioLevelSnapshot>({ db: -60, level: 0 })
  const [sys, setSys] = useState<AudioLevelSnapshot>({ db: -60, level: 0 })
  const rafRef = useRef<number>(0)

  useEffect(() => {
    if (!active) {
      setMic({ db: -60, level: 0 })
      setSys({ db: -60, level: 0 })
      return
    }
    let running = true
    const tick = () => {
      if (!running) return
      setMic(micLevelRef.current)
      if (systemEnabled) setSys(systemLevelRef.current)
      rafRef.current = requestAnimationFrame(tick)
    }
    tick()
    return () => {
      running = false
      cancelAnimationFrame(rafRef.current)
    }
  }, [active, systemEnabled, micLevelRef, systemLevelRef])

  return (
    <AudioLevelFooter
      active={active}
      paused={paused}
      mic={mic}
      system={systemEnabled ? sys : undefined}
    />
  )
}

const st: Record<string, CSSProperties> = {
  root: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: 16,
  },
  title: {
    fontSize: 10.5,
    fontWeight: 600,
    color: 'var(--text-dim)',
    letterSpacing: '0.08em',
    fontFamily: 'var(--mono)',
    textTransform: 'uppercase',
    minWidth: 92,
    flexShrink: 0,
  },
  channels: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
    gap: 12,
    width: '100%',
  },
  channel: {
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 5,
  },
  topline: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  bottomline: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) 62px',
    alignItems: 'center',
    gap: 10,
  },
  label: {
    fontSize: 11.5,
    color: 'var(--text)',
    fontWeight: 600,
  },
  db: {
    fontSize: 11,
    color: 'var(--text-muted)',
    fontFamily: 'var(--mono)',
    textAlign: 'right',
  },
  meterTrack: {
    height: 8,
    borderRadius: 999,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    overflow: 'hidden',
    minWidth: 0,
  },
  meterFill: {
    height: '100%',
    borderRadius: 999,
    transition: 'width 120ms linear, opacity 120ms linear',
  },
  status: {
    fontSize: 10.5,
    color: 'var(--text-dim)',
    fontFamily: 'var(--mono)',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
}
