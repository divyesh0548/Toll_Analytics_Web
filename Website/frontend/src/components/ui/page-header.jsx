import { cn } from '@/lib/utils'

/**
 * Anchors the first viewport: title block + actions with a soft bottom band.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}) {
  return (
    <div
      className={cn(
        'border-b border-border/80 pb-5',
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          {eyebrow ? (
            <div className="text-small text-muted-foreground">{eyebrow}</div>
          ) : null}
          {typeof title === 'string' ? (
            <h1 className="text-display">{title}</h1>
          ) : (
            title
          )}
          {description ? (
            <p className="text-body text-muted-foreground">{description}</p>
          ) : null}
          {children}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
    </div>
  )
}
