import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function parseIso(iso) {
  if (!iso) return null
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

function toIso(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function monthKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

function startOfMonth(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function formatDisplay(iso) {
  const d = parseIso(iso)
  if (!d) return 'Select date'
  return d.toLocaleDateString('en-IN', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function buildMonthCells(viewMonth, availableSet) {
  const first = startOfMonth(viewMonth)
  // Monday-based week
  const jsDay = first.getDay() // 0 Sun .. 6 Sat
  const mondayOffset = jsDay === 0 ? 6 : jsDay - 1
  const gridStart = new Date(first)
  gridStart.setDate(first.getDate() - mondayOffset)

  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(gridStart)
    d.setDate(gridStart.getDate() + i)
    const iso = toIso(d)
    cells.push({
      iso,
      day: d.getDate(),
      inMonth: d.getMonth() === viewMonth.getMonth(),
      available: availableSet.has(iso),
    })
  }
  return cells
}

/**
 * Calendar popover that only enables ISO dates present in `availableDates`.
 */
export function AvailableDatePicker({
  label,
  value,
  onChange,
  availableDates = [],
  className,
}) {
  const availableSet = useMemo(() => new Set(availableDates), [availableDates])
  const availableMonths = useMemo(() => {
    const keys = new Set()
    for (const iso of availableDates) {
      keys.add(iso.slice(0, 7))
    }
    return [...keys].sort()
  }, [availableDates])

  const initialMonth = useMemo(() => {
    const selected = parseIso(value)
    if (selected) return startOfMonth(selected)
    if (availableDates.length) {
      return startOfMonth(parseIso(availableDates[availableDates.length - 1]))
    }
    return startOfMonth(new Date())
  }, [value, availableDates])

  const [open, setOpen] = useState(false)
  const [viewMonth, setViewMonth] = useState(initialMonth)
  const rootRef = useRef(null)

  useEffect(() => {
    if (open) setViewMonth(initialMonth)
  }, [open, initialMonth])

  useEffect(() => {
    if (!open) return undefined
    function onDocClick(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const viewKey = monthKey(viewMonth)
  const monthIndex = availableMonths.indexOf(viewKey)
  const canPrev =
    monthIndex > 0 ||
    (monthIndex < 0 && availableMonths.some((m) => m < viewKey))
  const canNext =
    (monthIndex >= 0 && monthIndex < availableMonths.length - 1) ||
    (monthIndex < 0 && availableMonths.some((m) => m > viewKey))

  function goPrev() {
    if (monthIndex > 0) {
      const [y, m] = availableMonths[monthIndex - 1].split('-').map(Number)
      setViewMonth(new Date(y, m - 1, 1))
      return
    }
    const prev = availableMonths.filter((m) => m < viewKey).at(-1)
    if (prev) {
      const [y, m] = prev.split('-').map(Number)
      setViewMonth(new Date(y, m - 1, 1))
    }
  }

  function goNext() {
    if (monthIndex >= 0 && monthIndex < availableMonths.length - 1) {
      const [y, m] = availableMonths[monthIndex + 1].split('-').map(Number)
      setViewMonth(new Date(y, m - 1, 1))
      return
    }
    const next = availableMonths.find((m) => m > viewKey)
    if (next) {
      const [y, m] = next.split('-').map(Number)
      setViewMonth(new Date(y, m - 1, 1))
    }
  }

  const cells = buildMonthCells(viewMonth, availableSet)
  const title = viewMonth.toLocaleDateString('en-IN', {
    month: 'long',
    year: 'numeric',
  })

  return (
    <div ref={rootRef} className={cn('relative space-y-1', className)}>
      {label ? (
        <span className="block text-small text-muted-foreground">{label}</span>
      ) : null}
      <Button
        type="button"
        variant="outline"
        className="h-10 min-w-[12rem] justify-between px-3 font-normal"
        onClick={() => setOpen((v) => !v)}
        disabled={availableDates.length === 0}
      >
        <span className="truncate">{formatDisplay(value)}</span>
        <CalendarDays className="h-4 w-4 shrink-0 opacity-70" />
      </Button>

      {open ? (
        <div className="absolute left-0 z-40 mt-1 w-[17.5rem] rounded-sm border border-border bg-card p-3 text-card-foreground shadow-md">
          <div className="mb-2 flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={goPrev}
              disabled={!canPrev}
              aria-label="Previous month"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <p className="text-body font-medium">{title}</p>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={goNext}
              disabled={!canNext}
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          <div className="mb-1 grid grid-cols-7 gap-1 text-center text-small text-muted-foreground">
            {WEEKDAYS.map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell) => {
              const selected = cell.iso === value
              const disabled = !cell.available
              return (
                <button
                  key={cell.iso}
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onChange(cell.iso)
                    setOpen(false)
                  }}
                  className={cn(
                    'h-8 rounded-sm text-small',
                    !cell.inMonth && 'opacity-40',
                    disabled && 'cursor-not-allowed text-muted-foreground/40',
                    !disabled && !selected && 'hover:bg-accent hover:text-accent-foreground',
                    selected && 'bg-primary text-primary-foreground',
                    cell.available && !selected && cell.inMonth && 'font-medium text-foreground',
                  )}
                >
                  {cell.day}
                </button>
              )
            })}
          </div>

          <p className="mt-2 text-small text-muted-foreground">
            Only dates with loaded traffic are selectable.
          </p>
        </div>
      ) : null}
    </div>
  )
}
