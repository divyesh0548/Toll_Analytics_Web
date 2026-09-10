import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

const ToastContext = createContext(null)

const VARIANT_STYLES = {
  success: 'border-primary/30 bg-card',
  warning: 'border-border bg-card',
  error: 'border-destructive/40 bg-card',
}

const VARIANT_TITLE = {
  success: 'Success',
  warning: 'Notice',
  error: 'Error',
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timersRef = useRef(new Map())

  const dismissToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const showToast = useCallback(
    (message, variant = 'success') => {
      const id = Date.now() + Math.random()
      setToasts((prev) => [...prev.slice(-4), { id, message, variant }])
      const timer = setTimeout(() => dismissToast(id), 4500)
      timersRef.current.set(id, timer)
    },
    [dismissToast],
  )

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer))
      timersRef.current.clear()
    }
  }, [])

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[60] flex w-[min(92vw,22rem)] flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            aria-live="polite"
            className={cn(
              'pointer-events-auto rounded-sm border px-4 py-3 text-body text-card-foreground shadow-sm',
              VARIANT_STYLES[toast.variant] || VARIANT_STYLES.success,
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p
                  className={cn(
                    'font-medium',
                    toast.variant === 'error' ? 'text-destructive' : 'text-primary',
                  )}
                >
                  {VARIANT_TITLE[toast.variant] || 'Notice'}
                </p>
                <p className="mt-1 text-muted-foreground">{toast.message}</p>
              </div>
              <button
                type="button"
                className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Dismiss"
                onClick={() => dismissToast(toast.id)}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
