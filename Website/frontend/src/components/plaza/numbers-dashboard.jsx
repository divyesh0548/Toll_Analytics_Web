import { useState } from 'react'
import Chart from 'react-apexcharts'
import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AvailableDatePicker } from '@/components/plaza/available-date-picker'
import {
  LayoutClassDistribution,
  LayoutGap,
  LayoutMopDistribution,
  LayoutSummary,
  Kpi,
  baseChartOptions,
  chartColors,
  chartTheme,
  formatCount,
  formatMoney,
} from '@/components/plaza/numbers-tabs'
import {
  MAX_X_AXIS_LABELS,
  categoryTooltipXFormatter,
  categoryXAxis,
  dayMonthLabel,
  formatMoneyCompact,
  formatScaledRevenue,
  monthAxisGroups,
  resolveRevenueScale,
  scaleRevenueValues,
  uniqueMonthCount,
} from '@/lib/chart-axis'
import { cn } from '@/lib/utils'
import { useTheme } from '@/components/theme-provider'

const PERIOD_TABS = [
  { id: 'day', label: 'Day' },
  { id: 'mtd', label: 'Month' },
  { id: 'ytd', label: 'Year' },
]

const LANE_COLLAPSE_COUNT = 6
/** Inclusive calendar days required for the Day interval. */
const MIN_DAY_RANGE_DAYS = 5

function parseIsoDate(iso) {
  if (!iso) return null
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`)
  return Number.isNaN(d.getTime()) ? null : d
}

function toIsoDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDaysIso(iso, days) {
  const d = parseIsoDate(iso)
  if (!d) return ''
  d.setDate(d.getDate() + days)
  return toIsoDate(d)
}

function inclusiveDaySpan(startIso, endIso) {
  const start = parseIsoDate(startIso)
  const end = parseIsoDate(endIso)
  if (!start || !end) return 0
  return Math.floor((end.getTime() - start.getTime()) / 86400000) + 1
}

export function PeriodRangeControls({
  period,
  onPeriodChange,
  draft,
  onDraftChange,
  onApply,
  availability,
  disabled = false,
}) {
  const dates = availability?.dates || []
  const months = availability?.months || []
  const years = availability?.years || []

  const fromDayOptions = dates.filter((iso) => {
    if (!draft.end) return true
    // Keep enough room for a ≥5-day inclusive window ending at draft.end
    return iso <= addDaysIso(draft.end, -(MIN_DAY_RANGE_DAYS - 1))
  })
  const toDayOptions = dates.filter((iso) => {
    if (!draft.start) return true
    return iso >= addDaysIso(draft.start, MIN_DAY_RANGE_DAYS - 1)
  })

  const toMonthOptions = months.filter(
    (m) => !draft.start || String(m.value) >= String(draft.start),
  )
  const toYearOptions = years.filter(
    (y) => !draft.start || String(y) >= String(draft.start),
  )

  const daySpanOk =
    period !== 'day' ||
    inclusiveDaySpan(draft.start, draft.end) >= MIN_DAY_RANGE_DAYS
  const rangeOrderOk = !draft.start || !draft.end || draft.start <= draft.end
  const canApply =
    !disabled && Boolean(draft.start) && Boolean(draft.end) && rangeOrderOk && daySpanOk

  function handleFromDay(iso) {
    const next = { ...draft, start: iso }
    if (!next.end || next.end < addDaysIso(iso, MIN_DAY_RANGE_DAYS - 1)) {
      const fallback = dates.find((d) => d >= addDaysIso(iso, MIN_DAY_RANGE_DAYS - 1))
      next.end = fallback || ''
    }
    onDraftChange(next)
  }

  function handleToDay(iso) {
    onDraftChange({ ...draft, end: iso })
  }

  function handleFromMonth(value) {
    const next = { ...draft, start: value }
    if (!next.end || next.end < value) {
      const fallback = months.find((m) => String(m.value) >= value)
      next.end = fallback ? String(fallback.value) : value
    }
    onDraftChange(next)
  }

  function handleFromYear(value) {
    const next = { ...draft, start: value }
    if (!next.end || String(next.end) < String(value)) {
      const fallback = years.find((y) => String(y) >= String(value))
      next.end = fallback != null ? String(fallback) : value
    }
    onDraftChange(next)
  }

  return (
    <div
      className={cn(
        'flex flex-wrap items-end gap-3 rounded-sm border border-border bg-card p-3',
        disabled && 'pointer-events-none opacity-70',
      )}
    >
      <div className="space-y-1">
        <p className="text-small text-muted-foreground">Interval</p>
        <div className="flex flex-wrap gap-1">
          {PERIOD_TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onPeriodChange(item.id)}
              className={cn(
                'rounded-sm px-2 py-1 text-small',
                period === item.id
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-secondary text-secondary-foreground',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {period === 'day' && (
        <>
          <AvailableDatePicker
            label="From date"
            value={draft.start || ''}
            availableDates={fromDayOptions}
            onChange={handleFromDay}
          />
          <AvailableDatePicker
            label="To date"
            value={draft.end || ''}
            availableDates={toDayOptions}
            onChange={handleToDay}
          />
          {!daySpanOk && draft.start && draft.end ? (
            <p className="basis-full text-small text-destructive">
              Select at least {MIN_DAY_RANGE_DAYS} days (inclusive).
            </p>
          ) : null}
        </>
      )}

      {period === 'mtd' && (
        <>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">From month</span>
            <select
              className="h-10 min-w-[9rem] rounded-sm border border-input bg-background px-2 text-body"
              value={draft.start || ''}
              onChange={(e) => handleFromMonth(e.target.value)}
            >
              {months.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">To month</span>
            <select
              className="h-10 min-w-[9rem] rounded-sm border border-input bg-background px-2 text-body"
              value={draft.end || ''}
              onChange={(e) => onDraftChange({ ...draft, end: e.target.value })}
            >
              {toMonthOptions.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {period === 'ytd' && (
        <>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">From year</span>
            <select
              className="h-10 min-w-[6rem] rounded-sm border border-input bg-background px-2 text-body"
              value={draft.start || ''}
              onChange={(e) => handleFromYear(e.target.value)}
            >
              {years.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">To year</span>
            <select
              className="h-10 min-w-[6rem] rounded-sm border border-input bg-background px-2 text-body"
              value={draft.end || ''}
              onChange={(e) => onDraftChange({ ...draft, end: e.target.value })}
            >
              {toYearOptions.map((y) => (
                <option key={y} value={String(y)}>
                  {y}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      <button
        type="button"
        onClick={onApply}
        disabled={!canApply}
        className="h-10 rounded-sm bg-primary px-3 text-small text-primary-foreground disabled:pointer-events-none disabled:opacity-50"
      >
        Apply
      </button>
    </div>
  )
}

function NumbersLoadingOverlay({ label = 'Updating numbers…' }) {
  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center rounded-sm bg-background/75 backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="flex flex-col items-center gap-3 rounded-sm border border-border bg-card px-6 py-5 text-card-foreground shadow-sm">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-body font-medium">{label}</p>
        <p className="text-small text-muted-foreground">Fetching traffic for the selected range</p>
      </div>
    </div>
  )
}

function RevenueTrafficChart({ revenueDaily, trafficDaily, dark, height = 300 }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)

  const byDate = new Map()
  for (const row of trafficDaily || []) {
    if (!row?.date) continue
    byDate.set(row.date, {
      date: row.date,
      label: row.label || row.date,
      traffic: Number(row.traffic) || 0,
      revenue: null,
    })
  }
  for (const row of revenueDaily || []) {
    if (!row?.date) continue
    const existing = byDate.get(row.date) || {
      date: row.date,
      label: row.label || row.date,
      traffic: null,
      revenue: null,
    }
    existing.revenue = Number(row.revenue) || 0
    if (!existing.label) existing.label = row.label || row.date
    byDate.set(row.date, existing)
  }

  const points = Array.from(byDate.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  )
  if (!points.length) {
    return (
      <p className="text-body text-muted-foreground">
        No revenue or traffic for this period.
      </p>
    )
  }

  const isoDates = points.map((p) => p.date)
  const fullCategories =
    uniqueMonthCount(isoDates) > 3
      ? isoDates.map((iso) => dayMonthLabel(iso))
      : points.map((p) => p.label)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const monthGroups = monthAxisGroups(isoDates, theme.labelStyle)
  const rawRevenue = points.map((p) => p.revenue)
  const revenueScale = resolveRevenueScale(rawRevenue)
  const scaledRevenue = scaleRevenueValues(rawRevenue, revenueScale)

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'line',
      zoom: { enabled: false },
    },
    stroke: { width: [3, 3], curve: 'smooth' },
    colors: [colors.primary, colors.series[1]],
    xaxis: {
      type: 'category',
      categories: xAxis.categories,
      labels: xAxis.labels,
      ...(monthGroups ? { group: monthGroups } : {}),
    },
    yaxis: [
      {
        title: { text: revenueScale.axisTitle, style: { color: theme.foreColor } },
        labels: {
          formatter: (v) =>
            Number(v).toLocaleString('en-IN', {
              maximumFractionDigits: revenueScale.unitKey === 'rupee' ? 0 : 2,
            }),
          style: theme.labelStyle,
        },
      },
      {
        opposite: true,
        title: { text: 'Traffic (vehicles)', style: { color: theme.foreColor } },
        labels: {
          formatter: (v) => Number(v).toLocaleString('en-IN'),
          style: theme.labelStyle,
        },
      },
    ],
    legend: {
      position: 'top',
      horizontalAlign: 'left',
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: theme.tooltipTheme,
      shared: true,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: {
        formatter: (v, opts) => {
          if (v == null) return '—'
          const name = opts?.w?.globals?.seriesNames?.[opts.seriesIndex] || ''
          if (String(name).toLowerCase().includes('revenue')) {
            return formatScaledRevenue(v, revenueScale)
          }
          return `${Number(v).toLocaleString('en-IN')} vehicles`
        },
      },
    },
  }

  return (
    <Chart
      options={options}
      series={[
        { name: `Revenue (${revenueScale.shortUnit})`, data: scaledRevenue },
        { name: 'Traffic (vehicles)', data: points.map((p) => p.traffic) },
      ]}
      type="line"
      height={height}
    />
  )
}

function RevenueBarChart({
  rows,
  dark,
  height = 260,
  maxLabels = undefined,
}) {
  if (!rows?.length) {
    return <p className="text-body text-muted-foreground">No revenue in this period.</p>
  }
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const isoDates = rows.map((r) => r.date).filter(Boolean)
  const hasAlignedDates = isoDates.length === rows.length
  const fullCategories = hasAlignedDates && uniqueMonthCount(isoDates) > 3
    ? isoDates.map((iso) => dayMonthLabel(iso))
    : rows.map((r) => r.label)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle, maxLabels)
  const rawValues = rows.map((r) => Number(r.revenue) || 0)
  const revenueScale = resolveRevenueScale(rawValues)
  const values = scaleRevenueValues(rawValues, revenueScale)
  const monthGroups = hasAlignedDates
    ? monthAxisGroups(isoDates, theme.labelStyle)
    : undefined

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
      zoom: { enabled: false },
    },
    plotOptions: { bar: { columnWidth: '55%', borderRadius: 2 } },
    colors: [colors.primary],
    xaxis: {
      type: 'category',
      categories: xAxis.categories,
      labels: xAxis.labels,
      ...(monthGroups ? { group: monthGroups } : {}),
    },
    yaxis: {
      title: { text: revenueScale.axisTitle, style: { color: theme.foreColor } },
      labels: {
        formatter: (v) =>
          Number(v).toLocaleString('en-IN', {
            maximumFractionDigits: revenueScale.unitKey === 'rupee' ? 0 : 2,
          }),
        style: theme.labelStyle,
      },
    },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: {
        formatter: (v) => formatScaledRevenue(v, revenueScale),
      },
    },
    dataLabels: { enabled: false },
  }

  return (
    <Chart
      options={options}
      series={[{ name: `Revenue (${revenueScale.shortUnit})`, data: values }]}
      type="bar"
      height={height}
    />
  )
}

function MopMixChart({ mopMix, dark, height = 220 }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const sorted = [...(mopMix || [])].sort(
    (a, b) => (Number(a.count) || 0) - (Number(b.count) || 0),
  )
  const fullCategories = sorted.map((m) => m.mop)
  const values = sorted.map((m) => Number(m.count) || 0)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
      stacked: false,
    },
    plotOptions: {
      bar: {
        horizontal: false,
        columnWidth: '55%',
        distributed: true,
        borderRadius: 2,
      },
    },
    colors: colors.series,
    xaxis: {
      categories: xAxis.categories,
      labels: xAxis.labels,
    },
    yaxis: {
      title: { text: 'Traffic (vehicles)', style: { color: theme.foreColor } },
      labels: {
        formatter: (v) => Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    legend: { show: false },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: {
        formatter: (v) =>
          v == null ? '—' : `${Number(v).toLocaleString('en-IN')} vehicles`,
      },
    },
  }
  return (
    <Chart
      options={options}
      series={[{ name: 'Traffic (vehicles)', data: values }]}
      type="bar"
      height={height}
    />
  )
}

function ClassMixChart({ classMix, dark, height = 220 }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = classMix.map((c) => c.vehicle_class)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
    },
    plotOptions: { bar: { horizontal: true, barHeight: '70%' } },
    colors: [colors.primary],
    xaxis: {
      categories: xAxis.categories,
      title: { text: 'Traffic (vehicles)', style: { color: theme.foreColor, fontSize: '12px' } },
      labels: {
        formatter: (v) => Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    yaxis: {
      labels: { style: theme.labelStyle },
    },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: {
        formatter: (v) =>
          v == null ? '—' : `${Number(v).toLocaleString('en-IN')} vehicles`,
      },
    },
  }
  const series = [{ name: 'Traffic (vehicles)', data: classMix.map((c) => c.count) }]
  return <Chart options={options} series={series} type="bar" height={height} />
}

function LaneThroughputCard({ laneThroughput }) {
  const [expanded, setExpanded] = useState(false)
  const lanes = laneThroughput || []
  const needsToggle = lanes.length > LANE_COLLAPSE_COUNT
  const visible = expanded || !needsToggle ? lanes : lanes.slice(0, LANE_COLLAPSE_COUNT)

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <CardTitle>Lane throughput</CardTitle>
        <CardDescription>
          {lanes.length
            ? `${lanes.length} lanes · selected interval`
            : 'Lane counts for the selected window'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        {lanes.length ? (
          <>
            <div className="divide-y divide-border">
              {visible.map((lane) => (
                <div
                  key={lane.lane}
                  className="flex items-center justify-between py-2 text-body first:pt-0 last:pb-0"
                >
                  <span>{lane.lane}</span>
                  <span className="font-medium">{formatCount(lane.count)}</span>
                </div>
              ))}
            </div>
            {needsToggle ? (
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="mt-3 inline-flex items-center gap-1 self-start text-small font-medium text-primary hover:underline"
              >
                {expanded ? (
                  <>
                    Show less
                    <ChevronUp className="h-4 w-4" />
                  </>
                ) : (
                  <>
                    Expand all {lanes.length} lanes
                    <ChevronDown className="h-4 w-4" />
                  </>
                )}
              </button>
            ) : null}
          </>
        ) : (
          <p className="text-body text-muted-foreground">No lane data.</p>
        )}
      </CardContent>
    </Card>
  )
}

function topShare(items, nameKey, countKey = 'count') {
  if (!items?.length) return null
  const total = items.reduce((sum, row) => sum + (Number(row[countKey]) || 0), 0)
  if (total <= 0) return null
  const top = items.reduce((best, row) =>
    (Number(row[countKey]) || 0) > (Number(best[countKey]) || 0) ? row : best,
  )
  return {
    name: String(top[nameKey] ?? '—'),
    pct: Math.round((1000 * (Number(top[countKey]) || 0)) / total) / 10,
  }
}

function LayoutOverview({ data, dark }) {
  const { kpis, daily_trend, class_mix, mop_mix, lane_throughput, revenue } = data
  const topClass = topShare(class_mix, 'vehicle_class')
  const topMop = topShare(mop_mix, 'mop')
  const revenueDaily = revenue?.daily || []
  const trafficDaily = (daily_trend || []).filter((row) => row?.date && row.hour == null)

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi
          label="Revenue"
          value={formatMoneyCompact(kpis.revenue_period)}
          hint={data.range_label || 'Selected interval'}
        />
        <Kpi
          label="Traffic count"
          value={formatCount(kpis.traffic_period)}
          hint={data.range_label || 'Selected interval'}
        />
        <Kpi
          label="ARPT ₹/veh"
          value={kpis.arpt == null ? '—' : formatMoney(kpis.arpt)}
          hint="Selected-period revenue ÷ traffic"
        />
        <Kpi
          label="Avg monthly revenue"
          value={
            kpis.revenue_avg_monthly_year == null
              ? '—'
              : formatMoneyCompact(kpis.revenue_avg_monthly_year)
          }
          hint={
            kpis.revenue_avg_year
              ? `Year ${kpis.revenue_avg_year} (months with data)`
              : 'Current year'
          }
        />
        <Kpi
          label="Avg daily revenue"
          value={
            kpis.revenue_avg_daily_year == null
              ? '—'
              : formatMoneyCompact(kpis.revenue_avg_daily_year)
          }
          hint={
            kpis.revenue_avg_year
              ? `Year ${kpis.revenue_avg_year} (days with data)`
              : 'Current year'
          }
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Daily revenue &amp; traffic</CardTitle>
          <CardDescription>
            {data.range_label || 'Selected period'} · dual axis · no last-year comparison
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RevenueTrafficChart
            revenueDaily={revenueDaily}
            trafficDaily={
              trafficDaily.length
                ? trafficDaily
                : (daily_trend || []).reduce((acc, row) => {
                    if (!row?.date) return acc
                    const existing = acc.find((p) => p.date === row.date)
                    if (existing) {
                      existing.traffic =
                        (Number(existing.traffic) || 0) + (Number(row.traffic) || 0)
                    } else {
                      acc.push({
                        date: row.date,
                        label: row.label?.split(' ').slice(0, 2).join(' ') || row.date,
                        traffic: Number(row.traffic) || 0,
                      })
                    }
                    return acc
                  }, [])
            }
            dark={dark}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3 lg:items-stretch">
        <Card>
          <CardHeader>
            <CardTitle>Mode mix — ETC / cash / exempt</CardTitle>
            <CardDescription>
              {topMop ? `Top: ${topMop.name} (${topMop.pct}%)` : 'MOP share for selected period'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {mop_mix.length ? (
              <MopMixChart mopMix={mop_mix} dark={dark} />
            ) : (
              <p className="text-body text-muted-foreground">No MOP data.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Class mix</CardTitle>
            <CardDescription>
              {topClass
                ? `Top: ${topClass.name} (${topClass.pct}%)`
                : 'Vehicle class share'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {class_mix.length ? (
              <ClassMixChart classMix={class_mix} dark={dark} />
            ) : (
              <p className="text-body text-muted-foreground">No class data.</p>
            )}
          </CardContent>
        </Card>
        <LaneThroughputCard laneThroughput={lane_throughput} />
      </div>
    </div>
  )
}

function LayoutRevenue({ data, dark }) {
  const { kpis, revenue } = data
  const daily = revenue?.daily || []

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Period revenue"
          value={formatMoneyCompact(kpis.revenue_period)}
          hint={data.range_label}
        />
        <Kpi
          label="Period traffic"
          value={formatCount(kpis.traffic_period)}
          hint={data.range_label}
        />
        <Kpi
          label="ARPT ₹/veh"
          value={kpis.arpt == null ? '—' : formatMoney(kpis.arpt)}
          hint="Period revenue ÷ traffic"
        />
        <Kpi
          label="Fastag share"
          value={kpis.etc_share == null ? '—' : `${kpis.etc_share}%`}
          hint="Share of period traffic with Fastag (TAG) MOP"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Revenue — daily</CardTitle>
          <CardDescription>
            Bar chart for each day in {data.range_label || 'selected period'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <RevenueBarChart
            rows={daily}
            dark={dark}
            maxLabels={MAX_X_AXIS_LABELS}
            height={320}
          />
        </CardContent>
      </Card>
    </div>
  )
}

const LAYOUTS = [
  { id: 'overview', label: 'Overview' },
  { id: 'gap', label: 'Gap' },
  { id: 'class', label: 'Class distribution' },
  { id: 'mop', label: 'MOP distribution' },
  { id: 'summary', label: 'Summary' },
  { id: 'revenue', label: 'Revenue' },
]

export function PlazaNumbersDashboard({
  data,
  period,
  onPeriodChange,
  rangeDraft,
  onRangeDraftChange,
  onApplyRange,
  layout,
  onLayoutChange,
  loading = false,
}) {
  const { theme } = useTheme()
  const dark = theme === 'dark'

  if (!data) {
    return (
      <div className="relative min-h-[16rem]">
        <NumbersLoadingOverlay label="Loading numbers…" />
      </div>
    )
  }

  if (data.has_data === false) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No traffic data</CardTitle>
          <CardDescription>
            No analytics rows found for this plaza yet. Load plaza Excel data, then refresh.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="relative space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {LAYOUTS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onLayoutChange(item.id)}
              disabled={loading}
              className={cn(
                'rounded-sm px-3 py-1.5 text-small',
                layout === item.id
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-secondary text-secondary-foreground',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <PeriodRangeControls
        period={period}
        onPeriodChange={onPeriodChange}
        draft={rangeDraft}
        onDraftChange={onRangeDraftChange}
        onApply={onApplyRange}
        availability={data.availability}
        disabled={loading}
      />

      <div className="relative min-h-[12rem]">
        {loading ? <NumbersLoadingOverlay /> : null}
        <div className={cn('space-y-4', loading && 'pointer-events-none select-none')}>
          {layout === 'overview' && <LayoutOverview data={data} dark={dark} />}
          {layout === 'gap' && <LayoutGap data={data} dark={dark} />}
          {layout === 'class' && <LayoutClassDistribution data={data} dark={dark} />}
          {layout === 'mop' && <LayoutMopDistribution data={data} dark={dark} />}
          {layout === 'summary' && <LayoutSummary data={data} dark={dark} />}
          {layout === 'revenue' && <LayoutRevenue data={data} dark={dark} />}
        </div>
      </div>
    </div>
  )
}
