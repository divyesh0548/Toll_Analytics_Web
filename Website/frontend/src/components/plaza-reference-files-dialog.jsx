import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { cn } from '@/lib/utils'
import {
  deletePlazaReferenceFile,
  downloadPlazaReferenceFile,
  listPlazaReferenceFiles,
  uploadPlazaReferenceFile,
} from '@/lib/api'

const KINDS = [
  { value: 'rates', label: 'Rates' },
  { value: 'approved_exemption', label: 'Approved exemption' },
]

const KIND_LABEL = {
  rates: 'Rates',
  approved_exemption: 'Approved exemption',
}

function rangeText(row) {
  return `${row.valid_from} to ${row.valid_to || 'open'}`
}

const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function parseIso(iso) {
  if (!iso) return null
  const date = new Date(`${iso}T00:00:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

function toIso(date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function formatDisplay(iso) {
  const date = parseIso(iso)
  if (!date) return ''
  return date.toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function buildMonthCells(viewMonth) {
  const first = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1)
  const jsDay = first.getDay()
  const mondayOffset = jsDay === 0 ? 6 : jsDay - 1
  const gridStart = new Date(first)
  gridStart.setDate(first.getDate() - mondayOffset)
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(gridStart)
    date.setDate(gridStart.getDate() + i)
    cells.push({
      iso: toIso(date),
      day: date.getDate(),
      inMonth: date.getMonth() === viewMonth.getMonth(),
    })
  }
  return cells
}

function DateCalendarField({ label, value, onChange, placeholder, optional }) {
  const selected = parseIso(value)
  const [open, setOpen] = useState(false)
  const [viewMonth, setViewMonth] = useState(() => selected || new Date())

  useEffect(() => {
    if (open) setViewMonth(selected || new Date())
  }, [open, value]) // eslint-disable-line react-hooks/exhaustive-deps

  const cells = useMemo(() => buildMonthCells(viewMonth), [viewMonth])
  const title = viewMonth.toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })

  function shiftMonth(delta) {
    setViewMonth((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1))
  }

  return (
    <div className="space-y-1">
      <span className="block text-small text-muted-foreground">{label}</span>
      <Button
        type="button"
        variant="outline"
        className="h-10 w-full justify-between px-3 font-normal"
        onClick={() => setOpen((current) => !current)}
      >
        <span className={cn('truncate', !value && 'text-muted-foreground')}>
          {value ? formatDisplay(value) : placeholder}
        </span>
        <CalendarDays className="h-4 w-4 shrink-0" />
      </Button>
      {open ? (
        <div data-calendar-panel className="rounded-sm border border-border bg-card p-3 text-card-foreground">
          <div className="mb-2 flex items-center justify-between gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => shiftMonth(-1)}
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
              onClick={() => shiftMonth(1)}
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <div className="mb-1 grid grid-cols-7 gap-1 text-center text-small text-muted-foreground">
            {WEEKDAYS.map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {cells.map((cell) => {
              const isSelected = cell.iso === value
              return (
                <button
                  key={cell.iso}
                  type="button"
                  onClick={() => {
                    onChange(cell.iso)
                    setOpen(false)
                  }}
                  className={cn(
                    'h-8 rounded-sm text-small text-foreground',
                    !cell.inMonth && 'text-muted-foreground',
                    !isSelected && 'hover:bg-accent hover:text-accent-foreground',
                    isSelected && 'bg-primary font-medium text-primary-foreground',
                  )}
                >
                  {cell.day}
                </button>
              )
            })}
          </div>
          {optional && value ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              Clear date
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function PlazaReferenceFilesDialog({
  open,
  onClose,
  plazas,
  initialPlazaIdentifier,
}) {
  const [plazaIdentifier, setPlazaIdentifier] = useState('')
  const [kind, setKind] = useState('rates')
  const [validFrom, setValidFrom] = useState('')
  const [validTo, setValidTo] = useState('')
  const [file, setFile] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    setPlazaIdentifier(initialPlazaIdentifier || '')
    setError('')
    return undefined
  }, [open, initialPlazaIdentifier])

  useEffect(() => {
    if (!open || !plazaIdentifier) {
      setRows([])
      return undefined
    }
    let cancelled = false
    setLoading(true)
    setError('')
    listPlazaReferenceFiles(plazaIdentifier)
      .then((data) => {
        if (!cancelled) setRows(data.files || [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load files')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, plazaIdentifier])

  async function onUpload(event) {
    event.preventDefault()
    setError('')
    if (!plazaIdentifier) {
      setError('Select a plaza')
      return
    }
    if (!validFrom) {
      setError('Valid from is required')
      return
    }
    if (validTo && validTo < validFrom) {
      setError('Valid to must be on or after Valid from')
      return
    }
    if (!file) {
      setError('Choose an Excel file')
      return
    }
    const body = new FormData()
    body.set('plaza_identifier', plazaIdentifier)
    body.set('kind', kind)
    body.set('valid_from', validFrom)
    if (validTo) body.set('valid_to', validTo)
    body.set('file', file)
    setBusy(true)
    try {
      await uploadPlazaReferenceFile(body)
      const data = await listPlazaReferenceFiles(plazaIdentifier)
      setRows(data.files || [])
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setError(err.message || 'Could not upload the file')
    } finally {
      setBusy(false)
    }
  }

  async function onDownload(row) {
    setBusy(true)
    setError('')
    try {
      const data = await downloadPlazaReferenceFile(row.id)
      if (!data?.download_url) {
        setError('Download link missing')
        return
      }
      window.open(data.download_url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setError(err.message || 'Could not download the file')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(row) {
    const label = `${KIND_LABEL[row.kind] || row.kind} ${row.original_file_name} (${rangeText(row)})`
    if (!window.confirm(`Delete ${label}?`)) return
    setBusy(true)
    setError('')
    try {
      await deletePlazaReferenceFile(row.id)
      setRows((current) => current.filter((item) => item.id !== row.id))
    } catch (err) {
      setError(err.message || 'Could not delete the file')
    } finally {
      setBusy(false)
    }
  }

  const plazaOptions = (Array.isArray(plazas) ? plazas : []).map((plaza) => ({
    value: plaza.plaza_identifier,
    label: plaza.plaza_name || plaza.plaza_identifier,
  }))

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Configure rates and other files"
      description="These files are used on the next exception run when the month sits entirely inside the dates. Leave Valid to empty to keep the file open-ended. Uploading the same dates again replaces that file."
      className="max-w-2xl"
    >
      {error ? (
        <p className="mb-3 rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body">
          {error}
        </p>
      ) : null}

      <form className="space-y-3" onSubmit={onUpload}>
        <label className="block space-y-1">
          <span className="block text-small text-muted-foreground">Plaza</span>
          <SearchableSelect
            options={plazaOptions}
            value={plazaIdentifier}
            onChange={(value) => setPlazaIdentifier(value)}
            placeholder="Select plaza…"
            searchPlaceholder="Search plaza…"
          />
        </label>
        <label className="block space-y-1">
          <span className="block text-small text-muted-foreground">File type</span>
          <SearchableSelect
            options={KINDS}
            value={kind}
            onChange={(value) => setKind(value)}
            placeholder="Select type…"
            searchPlaceholder="Search…"
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <DateCalendarField
            label="Valid from"
            value={validFrom}
            onChange={setValidFrom}
            placeholder="Select start date"
          />
          <DateCalendarField
            label="Valid to (optional)"
            value={validTo}
            onChange={setValidTo}
            placeholder="Open-ended"
            optional
          />
        </div>
        <div className="space-y-1">
          <span className="block text-small text-muted-foreground">Excel file</span>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.xlsm,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="sr-only"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => fileInputRef.current?.click()}
            >
              Choose file
            </Button>
            <span className={cn('text-body', file ? 'text-foreground' : 'text-muted-foreground')}>
              {file ? file.name : 'No file selected'}
            </span>
          </div>
        </div>
        <Button type="submit" disabled={busy || !plazaIdentifier}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Upload
        </Button>
      </form>

      <div className="mt-6 space-y-2">
        <h3 className="text-header">Stored files</h3>
        {loading ? (
          <p className="flex items-center gap-2 text-body text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </p>
        ) : null}
        {!loading && plazaIdentifier && rows.length === 0 ? (
          <p className="text-body text-muted-foreground">No files stored for this plaza yet.</p>
        ) : null}
        {!plazaIdentifier ? (
          <p className="text-body text-muted-foreground">Select a plaza to see its files.</p>
        ) : null}
        {rows.map((row) => (
          <div
            key={row.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-border px-3 py-2"
          >
            <div>
              <p className="text-body font-medium">{row.original_file_name}</p>
              <p className="text-small text-muted-foreground">
                {KIND_LABEL[row.kind] || row.kind} · {rangeText(row)}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => onDownload(row)}
              >
                Download
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => onDelete(row)}
              >
                Delete
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Dialog>
  )
}
