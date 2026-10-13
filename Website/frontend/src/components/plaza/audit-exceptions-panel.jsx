import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { formatMoneyCompact } from '@/lib/chart-axis'
import { cn } from '@/lib/utils'

const LAC = 100_000

/** Absolute rupees → Lakh number only (no “Lakh” suffix; use in column header). */
function formatImpactLakh(value, { digits = 2 } = {}) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value) / LAC
  return n.toLocaleString('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

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

function formatCount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN')
}

function formatSharePct(amount, periodRevenue) {
  if (periodRevenue == null) return null
  const a = Number(amount)
  const t = Number(periodRevenue)
  if (!Number.isFinite(a) || !Number.isFinite(t) || t <= 0) return null
  return (a / t) * 100
}

/** Empty-result note when a metric row exists with zero transactions (month view). */
function emptyResultNote(line, { wholeYear }) {
  if (wholeYear) return null
  if (line?.percentage != null) return null
  if (Number(line?.total_count) !== 0) return null

  const code = String(line?.code || '').toUpperCase()
  const status = String(line?.status || '').trim().toLowerCase()
  const defaults = {
    empty_filter:
      code === 'E09' || code === 'E9'
        ? 'No UNSETTLED rows after filters'
        : code === 'E04' || code === 'E4'
          ? 'No qualifying passes after filters'
          : 'No transactions after filters',
    no_trips: 'No trips recorded for qualifying passes',
    no_amount: 'No countable unsettled amounts',
  }
  if (status === 'empty_filter' || status === 'no_trips' || status === 'no_amount') {
    return line?.notes || defaults[status] || defaults.empty_filter
  }
  if (line?.notes) {
    return String(line.notes)
  }
  // Metric recorded as zero without a status (common until writers set notes).
  if (line?.has_metric) {
    return 'No transactions recorded for this period'
  }
  return null
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
    wholeYear: true,
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
  metricsSource = 'manual',
  canApply = false,
  onYearChange,
  onMonthChange,
  onWholeYearChange,
  onMetricsSourceChange,
  onApply,
}) {
  const yearOptions = useMemo(
    () => buildAuditYearOptions(data?.availability?.years || [], yearValue || data?.selection?.year),
    [data, yearValue],
  )
  const exceptions = data?.exceptions || []
  const summary = data?.summary
  const periodRevenue =
    summary?.period_revenue != null ? Number(summary.period_revenue) : null
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
            Standard findings for this plaza by month or full year. Impact in ₹ Lakh.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1">
            <span className="block text-body text-foreground">Metrics source</span>
            <select
              className="h-10 min-w-[10rem] rounded-sm border border-input bg-background px-2 text-body"
              value={metricsSource || data?.metrics_source || 'manual'}
              onChange={(e) => onMetricsSourceChange?.(e.target.value)}
              disabled={loading}
            >
              <option value="manual">Manual upload</option>
              <option value="pipeline">File Upload</option>
            </select>
          </label>
          <label className="flex h-10 items-center gap-2">
            <Switch
              checked={Boolean(wholeYear)}
              onCheckedChange={(checked) => onWholeYearChange?.(Boolean(checked))}
              disabled={loading}
              aria-label="Whole year"
            />
            <span className="text-body text-foreground">Whole year</span>
          </label>
          <label className="space-y-1">
            <span className="block text-body text-foreground">Year</span>
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
              <span className="block text-body text-foreground">Month</span>
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
          {canApply ? (
            <Button
              type="button"
              className="h-10"
              disabled={loading}
              onClick={() => onApply?.()}
            >
              Apply
            </Button>
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
            <p className="text-body text-foreground">Findings</p>
            <p className="text-display text-2xl font-semibold tracking-tight">
              {formatCount(summary?.exception_types ?? 14)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <p className="text-body text-foreground">Total transactions</p>
            <p className="text-display text-2xl font-semibold tracking-tight">
              {formatCount(summary?.total_count)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-4">
            <p className="text-body text-foreground">Total Impact</p>
            <p className="text-display text-2xl font-semibold tracking-tight">
              {formatMoneyCompact(summary?.total_amount)}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className={cn(loading && 'opacity-70')}>
        <CardHeader>
          <CardTitle className="text-header">
            {data?.selection?.label || 'Selected period'}
          </CardTitle>
          <CardDescription className="text-body">
            Transactions and impact (₹ Lakh) for this plaza. % of Revenue is each
            exception’s share of plaza ETC revenue for the selected period. Output
            downloads match by month label (e.g. 2026-Apr-May shows for April and May).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && !exceptions.length ? (
            <p className="text-body text-muted-foreground">Loading audit exceptions…</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] border-collapse text-left text-body">
                <thead>
                  <tr className="border-b border-border text-foreground">
                    <th className="px-2 py-3 text-body font-semibold">Code</th>
                    <th className="px-2 py-3 text-body font-semibold">Exception</th>
                    <th className="px-2 py-3 text-body font-semibold text-right">
                      Transactions
                    </th>
                    <th className="px-2 py-3 text-body font-semibold text-right">
                      Impact (in Lakh)
                    </th>
                    <th className="px-2 py-3 text-body font-semibold text-right">
                      % of Revenue
                    </th>
                    <th className="px-2 py-3 text-body font-semibold text-right">Output</th>
                  </tr>
                </thead>
                <tbody>
                  {exceptions.flatMap((row) => {
                    const segmentRows = row.segments || []
                    return [row, ...segmentRows].map((line, index) => {
                      const nested = index > 0
                      const isPctMetric = line.percentage != null
                      const sharePct = isPctMetric
                        ? null
                        : formatSharePct(line.total_amount, periodRevenue)
                      const emptyNote = emptyResultNote(line, {
                        wholeYear: Boolean(wholeYear),
                      })
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
                              'px-2 py-3 text-base font-semibold whitespace-nowrap',
                              nested && 'pl-8',
                            )}
                          >
                            {line.code}
                          </td>
                          <td className="max-w-[28rem] px-2 py-3 text-base leading-snug">
                            <div>{line.label}</div>
                            {emptyNote ? (
                              <p className="mt-1 text-small text-muted-foreground">
                                {emptyNote}
                              </p>
                            ) : null}
                          </td>
                          <td className="px-2 py-3 text-right text-base font-semibold tabular-nums whitespace-nowrap">
                            {isPctMetric ? '—' : formatCount(line.total_count)}
                          </td>
                          <td className="px-2 py-3 text-right text-base font-semibold tabular-nums whitespace-nowrap">
                            {isPctMetric
                              ? `${Number(line.percentage).toFixed(2)}%`
                              : formatImpactLakh(line.total_amount)}
                          </td>
                          <td className="px-2 py-3 text-right text-base font-semibold tabular-nums whitespace-nowrap">
                            {sharePct == null ? '—' : `${sharePct.toFixed(2)}%`}
                          </td>
                          <td className="px-2 py-3 text-right whitespace-nowrap">
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
