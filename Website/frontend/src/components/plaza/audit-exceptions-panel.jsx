import { useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

function displayOrDash(value) {
  if (value == null || String(value).trim() === '') return '—'
  return String(value)
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
            Amount and count are plaza-specific. Severity and status are placeholders for now.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && !exceptions.length ? (
            <p className="text-body text-muted-foreground">Loading audit exceptions…</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] border-collapse text-left text-small">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Code</th>
                    <th className="px-2 py-2 font-medium">Exception</th>
                    <th className="px-2 py-2 font-medium text-right">Amount</th>
                    <th className="px-2 py-2 font-medium text-right">Count</th>
                    <th className="px-2 py-2 font-medium">Severity</th>
                    <th className="px-2 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {exceptions.map((row) => (
                    <tr key={row.code} className="border-b border-border/70 align-top">
                      <td className="px-2 py-2 font-medium whitespace-nowrap">{row.code}</td>
                      <td className="px-2 py-2 max-w-[28rem]">{row.label}</td>
                      <td className="px-2 py-2 text-right whitespace-nowrap">
                        {formatAmount(row.total_amount)}
                      </td>
                      <td className="px-2 py-2 text-right whitespace-nowrap">
                        {formatCount(row.total_count)}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">
                        {displayOrDash(row.severity)}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap">
                        {displayOrDash(row.status)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
