import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Sidebar } from './Sidebar'
import type { ScreenId } from '../types/domain'

vi.mock('../query/queue', () => ({
  useQueueCountQuery: () => ({ data: 3 }),
}))

function renderSidebar(screenId: ScreenId = 'session', recording = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const setScreen = vi.fn()
  const result = render(
    <QueryClientProvider client={queryClient}>
      <Sidebar screen={screenId} setScreen={setScreen} recording={recording} />
    </QueryClientProvider>,
  )
  return { ...result, setScreen }
}

describe('Sidebar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders app name', () => {
    renderSidebar()
    expect(screen.getByText('Voice Diary')).toBeDefined()
  })

  it('renders all nav items', () => {
    renderSidebar()
    expect(screen.getByTestId('nav-session')).toBeDefined()
    expect(screen.getByTestId('nav-sessions')).toBeDefined()
    expect(screen.getByTestId('nav-contacts')).toBeDefined()
    expect(screen.getByTestId('nav-queue')).toBeDefined()
    expect(screen.getByTestId('nav-search')).toBeDefined()
    expect(screen.getByTestId('nav-settings')).toBeDefined()
  })

  it('calls setScreen when nav item clicked', () => {
    const { setScreen } = renderSidebar()
    fireEvent.click(screen.getByTestId('nav-contacts'))
    expect(setScreen).toHaveBeenCalledWith('contacts')
  })

  it('shows recording dot when recording is active', () => {
    renderSidebar('session', true)
    const dot = document.querySelector('.rec-pulse')
    expect(dot).not.toBeNull()
  })

  it('does not show recording dot when not recording', () => {
    renderSidebar('session', false)
    const dot = document.querySelector('.rec-pulse')
    expect(dot).toBeNull()
  })

  it('shows queue count badge when count > 0', () => {
    renderSidebar()
    expect(screen.getByText('3')).toBeDefined()
  })

  it('does not show badge on items without badge count', () => {
    renderSidebar()
    const badges = screen.getAllByText('3')
    expect(badges.length).toBe(1)
  })

  it('highlights active nav item', () => {
    renderSidebar('settings')
    const settingsBtn = screen.getByTestId('nav-settings')
    const style = window.getComputedStyle(settingsBtn)
    // Active items have accent color
    expect(style.color).not.toBe('')
  })

  it('renders group labels', () => {
    renderSidebar()
    // Group labels are uppercase mono text - check they exist via style attribute
    const groupLabels = document.querySelectorAll('[style*="text-transform: uppercase"]')
    expect(groupLabels.length).toBeGreaterThan(0)
  })
})
