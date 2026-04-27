import type { ReactNode } from 'react'

export function highlight(text: string, query: string): ReactNode {
  if (!query) return text
  const i = text.toLowerCase().indexOf(query.toLowerCase())
  if (i === -1) return text
  return (
    <>
      {text.slice(0, i)}
      <mark
        style={{
          background: 'rgba(245,78,0,0.18)',
          color: 'var(--text)',
          borderRadius: 2,
          padding: '0 1px',
        }}
      >
        {text.slice(i, i + query.length)}
      </mark>
      {text.slice(i + query.length)}
    </>
  )
}
