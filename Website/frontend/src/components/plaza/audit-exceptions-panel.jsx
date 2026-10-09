import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

function formatAmount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
}

function formatCount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN')
}

function formatBytes(value) {
  const size = Number(value)
  if (!Number.isFinite(size) || size < 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

export function defaultAuditPeriod() {
  const now = new Date()
  return {
    year: String(now.getFullYear()),
    month: String(now.getMonth() + 1).padStart(2, '0'),
    wholeYear: false,
  }
}

/** Build year options from API availability + recent years + current selection. */
export function buildAuditYearOptions(availabilityYears = [], selectionYear) {
  const years = new Set(
    (availabilityYears || []).map((y) => Number(y)).filter((y) => Number.isFinite(y)),
  )
  const now = new Date().getFullYear()
  for (let offset = 0; offset < 6; offset += 1) {
    years.add(now - offset)
  }
  if (selectionYear) years.add(Number(selectionYear))
  return Array.from(years)
    .filter((y) => Number.isFinite(y))
    .sort((a, b) => b - a)
    .map((y) => String(y))
}

function OutputFilesDialog({ open, onClose, title, files }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title || 'Output files'}
      description="Downloads for this exception in the selected period."
      className="max-w-xl"
    >
      {!files?.length ? (
        <p className="text-body text-muted-foreground">No output files for this period.</p>
      ) : (
        <ul className="max-h-[24rem] space-y-2 overflow-auto">
          {files.map((file) => (
            <li
              key={file.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-border px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-body font-medium">
                  {file.original_file_name || file.file_name}
                </p>
                <p className="truncate text-small text-muted-foreground">
                  {file.month_label}
                  {file.file_size_bytes != null ? ` · ${formatBytes(file.file_size_bytes)}` : ''}
                  {file.file_name && file.original_file_name
                    ? ` · ${file.file_name}`
                    : ''}
                </p>
              </div>
              {file.file_url ? (
                <Button asChild size="sm" variant="outline">
                  <a href={file.file_url} target="_blank" rel="noreferrer">
                    <Download className="h-3.5 w-3.5" />
                    Download
                  </a>
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

function OutputCell({ line, wholeYear }) {
  const files = line.output_files || []
  const [open, setOpen] = useState(false)

  if (!files.length) {
    return <span className="text-muted-foreground">—</span>
  }

  if (wholeYear) {
    return (
      <>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          <Download className="h-3.5 w-3.5" />
          Outputs ({files.length})
        </Button>
        <OutputFilesDialog
          open={open}
          onClose={() => setOpen(false)}
          title={`${line.code} outputs`}
          files={files}
        />
      </>
    )
  }

  // Month view: one file → direct download; several → popup (multi-month / history).
  if (files.length === 1 && files[0].file_url) {
    const file = files[0]
    return (
      <Button asChild size="sm" variant="outline">
        <a
          href={file.file_url}
          target="_blank"
          rel="noreferrer"
          title={file.month_label || file.file_name}
        >
          <Download className="h-3.5 w-3.5" />
          Download
        </a>
      </Button>
    )
  }

  return (
    <>
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Download className="h-3.5 w-3.5" />
        Files ({files.length})
      </Button>
      <OutputFilesDialog
        open={open}
        onClose={() => setOpen(false)}
        title={`${line.code} outputs`}
        files={files}
      />
    </>
  )
}

export function AuditExceptionsPanel({
  data,
  loading = false,
  error = '',
  yearValue,
  monthValue,
  wholeYear = false,
  onYearChange,
  onMonthChange,
  onWholeYearChange,
}) {
  const yearOptions = useMemo(
    () => buildAuditYearOptions(data?.availability?.years || [], yearValue || data?.selection?.year),
    [data, yearValue],
  )
  const exceptions = data?.exceptions || []
  const summary = data?.summary
  const selectedYear = yearValue || (data?.selection?.year != null ? String(data.selection.year) : '')
  const selectedMonth =
    monthValue ||
    (data?.selection?.month != null
      ? String(data.selection.month).padStart(2, '0')
      : String(new Date().getMonth() + 1).padStart(2, '0'))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-header">Audit exceptions</h2>
          <p className="text-body text-muted-foreground">
            Standard findings for this plaza by month or full year.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex h-10 items-center gap-2">
            <Switch
              checked={Boolean(wholeYear)}
              onCheckedChange={(checked) => onWholeYearChange?.(Boolean(checked))}
              disabled={loading}
              aria-label="Whole year"
            />
            <span className="text-small text-muted-foreground">Whole year</span>
          </label>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">Year</span>
            <select
              className="h-10 min-w-[7rem] rounded-sm border border-input bg-background px-2 text-body"
              value={selectedYear}
              onChange={(e) => onYearChange?.(e.target.value)}
              disabled={loading}
            >
              {yearOptions.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </label>
          {!wholeYear ? (
            <label className="space-y-1">
              <span className="block text-small text-muted-foreground">Month</span>
              <select
                className="h-10 min-w-[8rem] rounded-sm border border-input bg-background px-2 text-body"
                value={selectedMonth}
                onChange={(e) => onMonthChange?.(e.target.value)}
                disabled={loading || !selectedYear}
              >
                {MONTH_NAMES.map((label, index) => {
                  const value = String(index + 1).padStart(2, '0')
                  return (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  )
                })}
              </select>
            </label>
          ) : null}
        </div>
      </div>

      {error ? (
        <Card>
          <CardHeader>
            <CardTitle>Audit exceptions unavailable</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="space-y-1 p-4">
            <p className="text-small text-muted-foreground">Findings</p>
            <p className="text-header">{formatCount(summary?.exception_types ?? 14)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <p className="text-small text-muted-foreground">Total amount</p>
            <p className="text-header">{formatAmount(summary?.total_amount)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <p className="text-small text-muted-foreground">Total count</p>
            <p className="text-header">{formatCount(summary?.total_count)}</p>
          </CardContent>
        </Card>
      </div>

      <Card className={cn(loading && 'opacity-70')}>
        <CardHeader>
          <CardTitle>
            {data?.selection?.label || 'Selected period'}
          </CardTitle>
          <CardDescription>
            Amount and count are plaza-specific for the selected period. Output downloads
            match by month label (e.g. 2026-Apr-May shows for April and May).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && !exceptions.length ? (
            <p className="text-body text-muted-foreground">Loading audit exceptions…</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[42rem] border-collapse text-left text-small">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Code</th>
                    <th className="px-2 py-2 font-medium">Exception</th>
                    <th className="px-2 py-2 font-medium text-right">Amount</th>
                    <th className="px-2 py-2 font-medium text-right">Count</th>
                    <th className="px-2 py-2 font-medium text-right">Output</th>
                  </tr>
                </thead>
                <tbody>
                  {exceptions.flatMap((row) => {
                    const segmentRows = row.segments || []
                    return [row, ...segmentRows].map((line, index) => {
                      const nested = index > 0
                      return (
                        <tr
                          key={line.code}
                          className={cn(
                            'border-b border-border/70 align-top',
                            nested && 'bg-muted/40',
                          )}
                        >
                          <td
                            className={cn(
                              'px-2 py-2 font-medium whitespace-nowrap',
                              nested && 'pl-8',
                            )}
                          >
                            {line.code}
                          </td>
                          <td className="px-2 py-2 max-w-[28rem]">{line.label}</td>
                          <td className="px-2 py-2 text-right whitespace-nowrap">
                            {line.percentage != null
                              ? `${Number(line.percentage).toFixed(2)}%`
                              : formatAmount(line.total_amount)}
                          </td>
                          <td className="px-2 py-2 text-right whitespace-nowrap">
                            {line.percentage != null ? '—' : formatCount(line.total_count)}
                          </td>
                          <td className="px-2 py-2 text-right whitespace-nowrap">
                            <OutputCell line={line} wholeYear={Boolean(wholeYear)} />
                          </td>
                        </tr>
                      )
                    })
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
