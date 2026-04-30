export type ToastType = 'error' | 'warning'

export interface Toast {
  id: string
  type: ToastType
  title: string
  message: string
  createdAt: number
  dismissTimer?: ReturnType<typeof setTimeout>
}

export interface ToastContextValue {
  toasts: Toast[]
  addToast: (opts: { type: ToastType; title: string; message: string }) => string
  removeToast: (id: string) => void
}
