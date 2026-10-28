import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function Dialog({ open, onClose, title, description, children, className }) {
  useEffect(() => {
    if (!open) return undefined
    function onKeyDown(event) {
      if (event.key !== 'Escape') return
      const tag = event.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      onClose?.()
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-black/50"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
        <div
          role="dialog"
          aria-modal="true"
          className={cn(
            'pointer-events-auto flex max-h-[calc(100dvh-3rem)] w-full max-w-lg flex-col overflow-hidden rounded-sm border border-border bg-card text-card-foreground shadow-none',
            className,
          )}
        >
          <div className="flex shrink-0 items-start justify-between gap-3 p-5 pb-4">
            <div className="space-y-1">
              {title ? <h2 className="text-header">{title}</h2> : null}
              {description ? <p className="text-body text-muted-foreground">{description}</p> : null}
            </div>
            <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-8">{children}</div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
