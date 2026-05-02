import { describe, expect, it, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useScreen } from './useScreen'

const STORAGE_KEY = 'vd_state'

beforeEach(() => {
  localStorage.clear()
})

describe('useScreen', () => {
  it('returns default screen when no value in localStorage', () => {
    const { result } = renderHook(() => useScreen('session'))
    expect(result.current[0]).toBe('session')
  })

  it('reads persisted screen from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ screen: 'contacts' }))
    const { result } = renderHook(() => useScreen('session'))
    expect(result.current[0]).toBe('contacts')
  })

  it('falls back to default when localStorage has invalid JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not-json')
    const { result } = renderHook(() => useScreen('settings'))
    expect(result.current[0]).toBe('settings')
  })

  it('falls back to default when screen field is missing', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ other: 1 }))
    const { result } = renderHook(() => useScreen('search'))
    expect(result.current[0]).toBe('search')
  })

  it('persists screen changes to localStorage', () => {
    const { result } = renderHook(() => useScreen('session'))

    act(() => {
      result.current[1]('contacts')
    })

    expect(result.current[0]).toBe('contacts')
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({ screen: 'contacts' })
  })

  it('survives localStorage errors on read', () => {
    const originalGetItem = localStorage.getItem
    localStorage.getItem = vi.fn(() => {
      throw new Error('quota exceeded')
    })

    const { result } = renderHook(() => useScreen('session'))
    expect(result.current[0]).toBe('session')

    localStorage.getItem = originalGetItem
  })

  it('survives localStorage errors on write', () => {
    const originalSetItem = localStorage.setItem
    localStorage.setItem = vi.fn(() => {
      throw new Error('quota exceeded')
    })

    const { result } = renderHook(() => useScreen('session'))

    act(() => {
      result.current[1]('search')
    })

    expect(result.current[0]).toBe('search')

    localStorage.setItem = originalSetItem
  })
})
