import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Shared hierarchy breadcrumb for company / SPV / plaza pages.
 * Pass `{ label, to? }` items; the last item is the current page (not linked).
 */
export function EntityBreadcrumb({ items = [], className }) {
  if (!items.length) return null

  return (
    <nav aria-label="Breadcrumb" className={cn('mb-3', className)}>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 text-body">
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          return (
            <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-1">
              {index > 0 && (
                <ChevronRight
                  className="mx-0.5 h-4 w-4 shrink-0 text-muted-foreground/45"
                  aria-hidden
                />
              )}
              {item.to && !isLast ? (
                <Link
                  to={item.to}
                  className="max-w-56 truncate rounded-sm px-1.5 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={item.label}
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  className={cn(
                    'max-w-64 truncate rounded-sm px-1.5 py-1',
                    isLast ? 'font-medium text-foreground' : 'text-muted-foreground',
                  )}
                  title={item.label}
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
