import { lazy, Suspense, useCallback, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Sidebar } from './components/Sidebar'
import { useScreen } from './hooks/useScreen'
import { useTranslation } from 'react-i18next'
import type { BackendStartupStatus } from './types/electron'
import type { ScreenId, Utterance } from './types/domain'

const AllSessions = lazy(() => import('./components/AllSessions').then(m => ({ default: m.AllSessions })))
const Contacts = lazy(() => import('./components/Contacts').then(m => ({ default: m.Contacts })))
const CurrentSession = lazy(() => import('./components/CurrentSession').then(m => ({ default: m.CurrentSession })))
const Search = lazy(() => import('./components/Search').then(m => ({ default: m.Search })))
const Settings = lazy(() => import('./components/Settings').then(m => ({ default: m.Settings })))
const UnknownQueue = lazy(() => import('./components/UnknownQueue').then(m => ({ default: m.UnknownQueue })))

interface EditModeMessage {
  type: string
  edits?: { startScreen?: ScreenId }
}

const startupStyles: Record<string, CSSProperties> = {
  shell: {
    minHeight: '100vh',
    display: 'grid',
    placeItems: 'center',
    background: 'var(--bg)',
    color: 'var(--text)',
    padding: 24,
  },
  panel: {
    width: 'min(460px, 100%)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    padding: 24,
    background: 'var(--surface)',
    boxShadow: '0 18px 60px rgba(0, 0, 0, 0.14)',
  },
  title: {
    margin: 0,
    fontSize: 22,
    lineHeight: 1.2,
  },
  body: {
    margin: '12px 0 0',
    color: 'var(--text-muted)',
    fontSize: 14,
    lineHeight: 1.5,
  },
  error: {
    marginTop: 14,
    padding: 12,
    border: '1px solid var(--record)',
    borderRadius: 6,
    color: 'var(--record)',
    fontFamily: 'var(--mono)',
    fontSize: 12,
    lineHeight: 1.4,
    overflowWrap: 'anywhere',
  },
}

function BackendStartupGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<BackendStartupStatus>(() => ({
    state: window.electronAPI ? 'starting' : 'ready',
    port: 8765,
    error: null,
  }))

  useEffect(() => {
    const api = window.electronAPI
    if (!api) return

    let cancelled = false
    const poll = async () => {
      try {
        const next = await api.getBackendStatus()
        if (!cancelled) setStatus(next)
      } catch (err) {
        if (!cancelled) {
          setStatus({
            state: 'error',
            port: 8765,
            error: err instanceof Error ? err.message : String(err),
          })
        }
      }
    }

    void poll()
    const interval = window.setInterval(() => {
      void poll()
    }, 1000)

    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [])

  if (status.state === 'ready') return <>{children}</>

  return (
    <main style={startupStyles.shell}>
      <section style={startupStyles.panel} aria-live="polite">
        <h1 style={startupStyles.title}>
          {status.state === 'error' ? t('startup.errorTitle') : t('startup.startingTitle')}
        </h1>
        <p style={startupStyles.body}>
          {status.state === 'error'
            ? t('startup.errorBody')
            : t('startup.startingBody', { port: status.port })}
        </p>
        {status.error && <pre style={startupStyles.error}>{status.error}</pre>}
      </section>
    </main>
  )
}

export function App() {
  const [screen, setScreen] = useScreen('session')
  const [recording, setRecording] = useState(false)
  const [utterances, setUtterances] = useState<Utterance[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  const applyLiveResolution = useCallback((segmentIds: string[], contactId: string) => {
    let previousUtterances: Utterance[] = []
    const idSet = new Set(segmentIds)

    setUtterances((current) => {
      previousUtterances = current
      let changed = false
      const next = current.map((utterance) => {
        if (!utterance.speakerSegmentId || !idSet.has(utterance.speakerSegmentId)) {
          return utterance
        }
        changed = true
        return { ...utterance, speakerId: contactId }
      })
      return changed ? next : current
    })

    return () => {
      setUtterances(previousUtterances)
    }
  }, [])

  useEffect(() => {
    const onMessage = (e: MessageEvent<EditModeMessage | undefined>) => {
      const data = e.data
      if (!data) return
      if (data.type === '__activate_edit_mode') {
        document.getElementById('tweak-panel')?.classList.add('visible')
      } else if (data.type === '__deactivate_edit_mode') {
        document.getElementById('tweak-panel')?.classList.remove('visible')
      } else if (data.type === '__edit_mode_set_keys') {
        const next = data.edits?.startScreen
        if (next) setScreen(next)
      }
    }
    window.addEventListener('message', onMessage)
    window.parent.postMessage({ type: '__edit_mode_available' }, '*')

    const sel = document.getElementById('tw-screen') as HTMLSelectElement | null
    const onSelChange = (e: Event) => {
      const target = e.target as HTMLSelectElement
      const next = target.value as ScreenId
      setScreen(next)
      window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { startScreen: next } }, '*')
    }
    sel?.addEventListener('change', onSelChange)

    return () => {
      window.removeEventListener('message', onMessage)
      sel?.removeEventListener('change', onSelChange)
    }
  }, [setScreen])

  return (
    <BackendStartupGate>
      <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
        <Sidebar
          screen={screen}
          setScreen={setScreen}
          recording={recording}
        />
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <Suspense fallback={null}>
            <div style={{ display: screen === 'session' ? 'block' : 'none', flex: 1, overflow: 'hidden' }}>
              <CurrentSession
                setRecording={setRecording}
                utterances={utterances}
                setUtterances={setUtterances}
                onSessionIdChange={setCurrentSessionId}
                onIdentifyUnknown={() => setScreen('queue')}
              />
            </div>
          </Suspense>
          {screen === 'sessions' && <Suspense fallback={null}><AllSessions /></Suspense>}
          {screen === 'queue' && (
            <Suspense fallback={null}>
              <UnknownQueue
                onApplyLiveResolution={applyLiveResolution}
                currentSessionId={currentSessionId}
              />
            </Suspense>
          )}
          {screen === 'contacts' && <Suspense fallback={null}><Contacts /></Suspense>}
          {screen === 'search' && <Suspense fallback={null}><Search /></Suspense>}
          {screen === 'settings' && <Suspense fallback={null}><Settings /></Suspense>}
        </div>
      </div>
    </BackendStartupGate>
  )
}
