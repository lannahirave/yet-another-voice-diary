import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Toggle } from './Toggle'

describe('Toggle', () => {
  it('calls onChange with true when clicked while off', () => {
    const onChange = vi.fn()
    const { container } = render(<Toggle on={false} onChange={onChange} />)
    fireEvent.click(container.firstChild as HTMLElement)
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('calls onChange with false when clicked while on', () => {
    const onChange = vi.fn()
    const { container } = render(<Toggle on={true} onChange={onChange} />)
    fireEvent.click(container.firstChild as HTMLElement)
    expect(onChange).toHaveBeenCalledWith(false)
  })

  it('does not call onChange when disabled', () => {
    const onChange = vi.fn()
    const { container } = render(<Toggle on={false} onChange={onChange} disabled />)
    fireEvent.click(container.firstChild as HTMLElement)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('renders with custom data-testid', () => {
    const onChange = vi.fn()
    render(<Toggle on={false} onChange={onChange} dataTestId="custom-toggle" />)
    expect(screen.getByTestId('custom-toggle')).toBeDefined()
  })

  it('applies disabled cursor style when disabled', () => {
    const onChange = vi.fn()
    const { container } = render(<Toggle on={false} onChange={onChange} disabled />)
    const el = container.firstChild as HTMLElement
    const style = window.getComputedStyle(el)
    expect(style.cursor).toBe('default')
  })

  it('applies pointer cursor when not disabled', () => {
    const onChange = vi.fn()
    const { container } = render(<Toggle on={false} onChange={onChange} />)
    const el = container.firstChild as HTMLElement
    const style = window.getComputedStyle(el)
    expect(style.cursor).toBe('pointer')
  })
})
