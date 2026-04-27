import { useEffect, useState } from 'react'
import type { ScreenId } from '../types/domain'

const STORAGE_KEY = 'vd_state'

function readSavedScreen(defaultScreen: ScreenId): ScreenId {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaultScreen
    const parsed = JSON.parse(raw) as { screen?: ScreenId }
    return parsed.screen ?? defaultScreen
  } catch {
    return defaultScreen
  }
}

export function useScreen(defaultScreen: ScreenId = 'session') {
  const [screen, setScreen] = useState<ScreenId>(() => readSavedScreen(defaultScreen))

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ screen }))
    } catch {
      /* ignore quota / private-mode errors */
    }
  }, [screen])

  return [screen, setScreen] as const
}
