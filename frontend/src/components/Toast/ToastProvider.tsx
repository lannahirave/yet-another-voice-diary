import { createContext, useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Toaster } from './Toaster'
import type { Toast, ToastContextValue, ToastType } from './types'

export const ToastContext = createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => {
      const t = prev.find((toast) => toast.id === id)
      if (t?.dismissTimer) clearTimeout(t.dismissTimer)
      return prev.filter((toast) => toast.id !== id)
    })
  }, [])

  const addToast = useCallback(
    (opts: { type: ToastType; title: string; message: string }) => {
      const id = crypto.randomUUID()
      const toast: Toast = {
        id,
        type: opts.type,
        title: opts.title,
        message: opts.message,
        createdAt: Date.now(),
      }
      toast.dismissTimer = setTimeout(() => removeToast(id), 6000)
      setToasts((prev) => [...prev, toast])
      return id
    },
    [removeToast],
  )

  useEffect(() => {
    return () => {
      toasts.forEach((t) => {
        if (t.dismissTimer) clearTimeout(t.dismissTimer)
      })
    }
  }, [toasts])

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      <Toaster />
    </ToastContext.Provider>
  )
}
