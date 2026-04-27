import { useCallback, useEffect, useState } from 'react'
import { AllSessions } from './components/AllSessions'
import { Contacts } from './components/Contacts'
import { CurrentSession } from './components/CurrentSession'
import { Search } from './components/Search'
import { Settings } from './components/Settings'
import { Sidebar } from './components/Sidebar'
import { UnknownQueue } from './components/UnknownQueue'
import { useScreen } from './hooks/useScreen'
import type { ScreenId, Utterance } from './types/domain'

interface EditModeMessage {
  type: string
  edits?: { startScreen?: ScreenId }
}

export function App() {
  const [screen, setScreen] = useScreen('session')
  const [recording, setRecording] = useState(false)
  const [utterances, setUtterances] = useState<Utterance[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  const applyLiveResolution = useCallback((segmentIds: string[], contactId: string) => {
    let previousUtterances: Utterance[] = []

    setUtterances((current) => {
      previousUtterances = current
      let changed = false
      const next = current.map((utterance) => {
        if (!utterance.speakerSegmentId || !segmentIds.includes(utterance.speakerSegmentId)) {
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
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar
        screen={screen}
        setScreen={setScreen}
        recording={recording}
      />
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: screen === 'session' ? 'block' : 'none', flex: 1, overflow: 'hidden' }}>
          <CurrentSession
            setRecording={setRecording}
            utterances={utterances}
            setUtterances={setUtterances}
            onSessionIdChange={setCurrentSessionId}
            onIdentifyUnknown={() => setScreen('queue')}
          />
        </div>
        {screen === 'sessions' && <AllSessions />}
        {screen === 'queue' && (
          <UnknownQueue
            onApplyLiveResolution={applyLiveResolution}
            currentSessionId={currentSessionId}
          />
        )}
        {screen === 'contacts' && <Contacts />}
        {screen === 'search' && <Search />}
        {screen === 'settings' && <Settings />}
      </div>
    </div>
  )
}
