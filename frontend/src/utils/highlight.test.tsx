import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { highlight } from './highlight'

describe('highlight', () => {
  it('returns plain text when query is empty', () => {
    const result = highlight('Hello World', '')
    expect(result).toBe('Hello World')
  })

  it('returns plain text when no match found', () => {
    const result = highlight('Hello World', 'xyz')
    expect(result).toBe('Hello World')
  })

  it('highlights matching substring case-insensitively', () => {
    const result = highlight('Hello World', 'world')
    const { container } = render(<>{result}</>)
    const mark = container.querySelector('mark')
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe('World')
  })

  it('highlights first match only', () => {
    const result = highlight('Hello hello hElLo', 'hello')
    const { container } = render(<>{result}</>)
    expect(container.querySelectorAll('mark').length).toBe(1)
  })

  it('returns JSX with surrounding text and mark', () => {
    const result = highlight('Before hello after', 'hello')
    const { container } = render(<>{result}</>)
    expect(container.textContent).toBe('Before hello after')
    expect(container.querySelector('mark')).not.toBeNull()
  })

  it('highlights query at start of text', () => {
    const result = highlight('hello after', 'hello')
    const { container } = render(<>{result}</>)
    const mark = container.querySelector('mark')
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe('hello')
    expect(container.textContent).toBe('hello after')
  })

  it('highlights query at end of text', () => {
    const result = highlight('before hello', 'hello')
    const { container } = render(<>{result}</>)
    const mark = container.querySelector('mark')
    expect(mark).not.toBeNull()
    expect(mark!.textContent).toBe('hello')
    expect(container.textContent).toBe('before hello')
  })
})
