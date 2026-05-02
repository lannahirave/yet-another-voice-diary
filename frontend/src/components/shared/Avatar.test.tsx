import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Avatar } from './Avatar'
import type { Contact } from '../../types/domain'

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: 'c1',
    name: 'John Doe',
    initials: 'JD',
    color: '#7C6FFF',
    sessions: 3,
    totalTime: 0,
    firstMet: 'January 2026',
    languages: [],
    profileCount: 2,
    confidence: 0.8,
    pitch: 'середній',
    tempo: 'середній',
    energy: 0,
    pitchHz: 0,
    ...overrides,
  }
}

describe('Avatar', () => {
  it('renders contact initials', () => {
    render(<Avatar contact={makeContact()} />)
    expect(screen.getByText('JD')).toBeDefined()
  })

  it('renders single initial for single-word name', () => {
    render(<Avatar contact={makeContact({ initials: 'A', name: 'Alice' })} />)
    expect(screen.getByText('A')).toBeDefined()
  })

  it('renders question mark when contact is null', () => {
    render(<Avatar contact={null} />)
    expect(screen.getByText('?')).toBeDefined()
  })

  it('applies custom size', () => {
    render(<Avatar contact={makeContact()} size={48} />)
    const el = screen.getByText('JD')
    const style = window.getComputedStyle(el)
    expect(style.width).toBe('48px')
    expect(style.height).toBe('48px')
  })

  it('applies default size 32', () => {
    render(<Avatar contact={makeContact()} />)
    const el = screen.getByText('JD')
    const style = window.getComputedStyle(el)
    expect(style.width).toBe('32px')
    expect(style.height).toBe('32px')
  })

  it('renders with border for null contact', () => {
    render(<Avatar contact={null} />)
    const el = screen.getByText('?')
    const style = el.getAttribute('style') || ''
    expect(style).toContain('dashed')
  })

  it('renders with border for known contact', () => {
    render(<Avatar contact={makeContact()} />)
    const el = screen.getByText('JD')
    const style = el.getAttribute('style') || ''
    expect(style).toContain('solid')
  })
})
