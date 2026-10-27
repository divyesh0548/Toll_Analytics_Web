import { useEffect } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function Dialog({ open, onClose, title, description, children, className }) {
  useEffect(() => {
    if (!open) return undefined
    function onKeyDown(event) {
      if (event.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', onKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50">
      <button
        type="button"
        className="fixed inset-0 cursor-default"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div className="relative z-10 flex min-h-full items-center justify-center px-4 pt-8 pb-16">
        <div
          role="dialog"
          aria-modal="true"
          className={cn(
            'flex max-h-[calc(100dvh-7.5rem)] w-full max-w-lg flex-col overflow-hidden rounded-sm border border-border bg-card text-card-foreground shadow-none',
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
          <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8">{children}</div>
        </div>
      </div>
    </div>
  )
}
