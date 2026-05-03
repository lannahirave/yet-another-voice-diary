import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useState, memo, useCallback, useMemo } from 'react'
import type { ReactNode } from 'react'

interface CompProps {
  label: string
  items?: string[]
}

function TestComp({ label, items }: CompProps) {
  const [count, setCount] = useState(0)
  const doubled = useMemo(() => count * 2, [count])
  const increment = useCallback(() => setCount((c) => c + 1), [])
  return (
    <div data-testid="comp">
      <span data-testid="label">{label}</span>
      <span data-testid="count">{count}</span>
      <span data-testid="doubled">{doubled}</span>
      <button data-testid="inc" onClick={increment}>
        +
      </button>
      {items?.map((item, i) => (
        <span key={i} data-testid={`item-${i}`}>
          {item}
        </span>
      ))}
    </div>
  )
}

const MemoizedComp = memo(function MemoizedComp({ label }: { label: string }) {
  return <div data-testid="memo-comp">{label}</div>
})

describe('React Compiler', () => {
  it('renders component with hooks correctly', () => {
    render(<TestComp label="test" />)
    expect(screen.getByTestId('label').textContent).toBe('test')
    expect(screen.getByTestId('count').textContent).toBe('0')
    expect(screen.getByTestId('doubled').textContent).toBe('0')
  })

  it('renders same component multiple times with different props', () => {
    const { rerender } = render(<TestComp label="first" />)
    expect(screen.getByTestId('label').textContent).toBe('first')

    rerender(<TestComp label="second" />)
    expect(screen.getByTestId('label').textContent).toBe('second')

    rerender(<TestComp label="third" />)
    expect(screen.getByTestId('label').textContent).toBe('third')
  })

  it('renders with optional props', () => {
    render(
      <TestComp label="with-items" items={['a', 'b', 'c']} />,
    )
    expect(screen.getByTestId('item-0').textContent).toBe('a')
    expect(screen.getByTestId('item-1').textContent).toBe('b')
    expect(screen.getByTestId('item-2').textContent).toBe('c')
  })

  it('renders memo component with compiler active', () => {
    const { rerender } = render(<MemoizedComp label="memo-test" />)
    expect(screen.getByTestId('memo-comp').textContent).toBe('memo-test')

    rerender(<MemoizedComp label="memo-test" />)
    expect(screen.getByTestId('memo-comp').textContent).toBe('memo-test')
  })

  it('renders nested components with compiler active', () => {
    function Inner({ text }: { text: ReactNode }) {
      return <span data-testid="inner">{text}</span>
    }

    function Outer({ children }: { children: ReactNode }) {
      return <div data-testid="outer">{children}</div>
    }

    render(
      <Outer>
        <Inner text="nested" />
      </Outer>,
    )

    expect(screen.getByTestId('outer')).toBeDefined()
    expect(screen.getByTestId('inner').textContent).toBe('nested')
  })
})
