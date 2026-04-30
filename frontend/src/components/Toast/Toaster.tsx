import { createPortal } from 'react-dom'
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useToast } from './useToast'

export function Toaster() {
  const { toasts, removeToast } = useToast()
  const [exitingIds, setExitingIds] = useState<Set<string>>(new Set())
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!containerRef.current) {
      containerRef.current = document.createElement('div')
      containerRef.current.id = 'toast-container'
      document.body.appendChild(containerRef.current)
    }
    return () => {
      if (containerRef.current) {
        containerRef.current.remove()
        containerRef.current = null
      }
    }
  }, [])

  const handleDismiss = (id: string) => {
    setExitingIds((prev) => new Set(prev).add(id))
    setTimeout(() => removeToast(id), 200)
  }

  if (!containerRef.current) return null

  return createPortal(
    <div style={stS.container} aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="alert"
          style={{
            ...stS.toast,
            ...(t.type === 'error' ? stS.toastError : stS.toastWarning),
            ...(exitingIds.has(t.id) ? stS.toastExit : stS.toastEnter),
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={stS.title}>{t.title}</div>
            <div style={stS.message}>{t.message}</div>
          </div>
          <button
            onClick={() => handleDismiss(t.id)}
            style={stS.dismiss}
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      ))}
    </div>,
    containerRef.current,
  )
}

const stS: Record<string, CSSProperties> = {
  container: {
    position: 'fixed',
    bottom: 20,
    right: 20,
    zIndex: 9999,
    display: 'flex',
    flexDirection: 'column-reverse',
    gap: 10,
    pointerEvents: 'none',
    maxHeight: 'calc(100vh - 40px)',
    overflowY: 'auto',
  },
  toast: {
    pointerEvents: 'auto',
    display: 'flex',
    position: 'relative',
    minWidth: 280,
    maxWidth: 360,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-md, 8px)',
    padding: '12px 14px',
    boxShadow: 'rgba(0,0,0,0.14) 0px 8px 24px, rgba(0,0,0,0.06) 0px 4px 12px',
  },
  toastError: {
    borderLeft: '4px solid var(--record, #cf2d56)',
  },
  toastWarning: {
    borderLeft: '4px solid var(--amber, #c08532)',
  },
  title: {
    fontFamily: 'var(--sans)',
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text)',
    marginBottom: 2,
    lineHeight: 1.4,
    paddingRight: 18,
  },
  message: {
    fontFamily: 'var(--mono)',
    fontSize: 11,
    color: 'var(--text-soft, var(--text-muted))',
    lineHeight: 1.55,
    wordBreak: 'break-word',
    paddingRight: 18,
  },
  dismiss: {
    position: 'absolute',
    top: 8,
    right: 10,
    background: 'none',
    border: 'none',
    color: 'var(--text-dim, var(--text-muted))',
    fontSize: 12,
    cursor: 'pointer',
    padding: 2,
    lineHeight: 1,
  },
  toastEnter: {
    animation: 'toast-slide-in 250ms ease-out forwards',
  },
  toastExit: {
    animation: 'toast-fade-out 200ms ease-in forwards',
  },
}
