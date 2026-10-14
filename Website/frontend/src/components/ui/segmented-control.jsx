import { cn } from '@/lib/utils'

/**
 * Compact segmented control for Day/Month/Year, layout chips, etc.
 * items: [{ id, label }]
 */
export function SegmentedControl({
  items = [],
  value,
  onChange,
  disabled = false,
  size = 'md',
  className,
}) {
  return (
    <div
      role="tablist"
      className={cn(
        'inline-flex flex-wrap rounded-sm border border-border bg-background p-0.5',
        disabled && 'pointer-events-none opacity-60',
        className,
      )}
    >
      {items.map((item) => {
        const selected = value === item.id
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            disabled={disabled}
            onClick={() => onChange?.(item.id)}
            className={cn(
              'rounded-sm text-small transition-colors',
              size === 'sm' ? 'px-2 py-1' : 'px-3 py-1.5',
              selected
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * Underline tabs for page-level sections (Numbers / Traffic / Audit).
 * items: [{ id, label, to?, target? }] — use `render` via map in parent for Links.
 */
export function UnderlineTabs({ className, children }) {
  return (
    <div
      className={cn(
        'flex flex-wrap gap-0 border-b border-border',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function underlineTabClass(active) {
  return cn(
    'relative -mb-px border-b-2 px-3 py-2 text-small transition-colors',
    active
      ? 'border-primary font-medium text-foreground'
      : 'border-transparent text-muted-foreground hover:text-foreground',
  )
}
