import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/**
 * Searchable single-select for parent company.
 * options: [{ value, label, meta? }]
 */
export function SearchableSelect({
  options = [],
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  emptyText = 'No matches',
  disabled = false,
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef(null)

  const selected = options.find((opt) => opt.value === value) || null

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter((opt) => {
      const haystack = `${opt.label} ${opt.meta || ''}`.toLowerCase()
      return haystack.includes(q)
    })
  }, [options, query])

  useEffect(() => {
    function onDocClick(event) {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        disabled={disabled}
        className={cn(
          'flex h-10 w-full items-center justify-between rounded-sm border border-input bg-background px-3 text-left text-body',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          disabled && 'opacity-50',
        )}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={cn(!selected && 'text-muted-foreground')}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full rounded-sm border border-border bg-card p-2">
          <div className="relative mb-2">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              className="pl-8"
              autoFocus
            />
          </div>
          <div className="max-h-56 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="px-2 py-3 text-small text-muted-foreground">{emptyText}</p>
            ) : (
              filtered.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={cn(
                    'flex w-full flex-col gap-0.5 rounded-sm px-2 py-2 text-left text-body hover:bg-accent',
                    opt.value === value && 'bg-accent',
                  )}
                  onClick={() => {
                    onChange?.(opt.value, opt)
                    setOpen(false)
                    setQuery('')
                  }}
                >
                  <span>{opt.label}</span>
                  {opt.meta ? (
                    <span className="text-small text-muted-foreground">{opt.meta}</span>
                  ) : null}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
