import Chart from 'react-apexcharts'
import { Loader2 } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AvailableDatePicker } from '@/components/plaza/available-date-picker'
import { categoryTooltipXFormatter, categoryXAxis } from '@/lib/chart-axis'
import { cn } from '@/lib/utils'
import { useTheme } from '@/components/theme-provider'

function formatCount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN')
}

function formatPct(value) {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}%`
}

const PERIOD_TABS = [
  { id: 'day', label: 'Day' },
  { id: 'mtd', label: 'Month' },
  { id: 'ytd', label: 'Year' },
]

function PeriodRangeControls({
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
            availableDates={dates}
            onChange={(iso) => onDraftChange({ ...draft, start: iso })}
          />
          <AvailableDatePicker
            label="To date"
            value={draft.end || ''}
            availableDates={dates}
            onChange={(iso) => onDraftChange({ ...draft, end: iso })}
          />
        </>
      )}

      {period === 'mtd' && (
        <>
          <label className="space-y-1">
            <span className="block text-small text-muted-foreground">From month</span>
            <select
              className="h-10 min-w-[9rem] rounded-sm border border-input bg-background px-2 text-body"
              value={draft.start || ''}
              onChange={(e) => onDraftChange({ ...draft, start: e.target.value })}
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
              {months.map((m) => (
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
              onChange={(e) => onDraftChange({ ...draft, start: e.target.value })}
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
              {years.map((y) => (
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
        disabled={disabled || !draft.start || !draft.end}
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

function chartColors(dark) {
  return {
    primary: dark ? '#6fbf7a' : '#2f7a45',
    muted: dark ? '#9ca3af' : '#94a3b8',
    series: dark
      ? ['#6fbf7a', '#93c5fd', '#fbbf24', '#f87171']
      : ['#2f7a45', '#2563eb', '#d97706', '#dc2626'],
  }
}

/** ApexCharts text / axis / legend colors for light vs dark UI. */
function chartTheme(dark) {
  const text = dark ? '#e5e7eb' : '#334155'
  const muted = dark ? '#cbd5e1' : '#64748b'
  return {
    foreColor: text,
    labelStyle: { colors: text, fontSize: '11px' },
    mutedLabelStyle: { colors: muted, fontSize: '11px' },
    legend: {
      labels: { colors: text },
    },
    gridBorder: dark ? '#3f3f46' : '#e5e7eb',
    tooltipTheme: dark ? 'dark' : 'light',
  }
}

function baseChartOptions(dark) {
  const theme = chartTheme(dark)
  return {
    chart: {
      foreColor: theme.foreColor,
      fontFamily: 'Archivo, sans-serif',
      toolbar: { show: false },
      background: 'transparent',
    },
    theme: { mode: dark ? 'dark' : 'light' },
    grid: { borderColor: theme.gridBorder },
    legend: {
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: theme.tooltipTheme,
    },
    dataLabels: { enabled: false },
  }
}

function Kpi({ label, value, hint }) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-small text-muted-foreground">{label}</p>
        <p className="text-header">{value}</p>
        {hint ? <p className="text-small text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  )
}

function DailyTrendChart({ dailyTrend, dark, height = 280, grain = 'day' }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = dailyTrend.map((d) => d.label || d.weekday)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const thisYear = dailyTrend.map((d) => d.traffic)
  const lastYear = dailyTrend.map((d) => d.traffic_ly)
  const hasLy = lastYear.some((v) => v != null)
  const seriesName = grain === 'hour' ? 'Traffic (hourly)' : 'Traffic'

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'line',
      zoom: { enabled: false },
    },
    stroke: { width: [3, 2], curve: 'smooth', dashArray: [0, 6] },
    colors: [colors.primary, colors.muted],
    xaxis: {
      categories: xAxis.categories,
      labels: xAxis.labels,
      title: { style: { color: theme.foreColor } },
    },
    yaxis: {
      labels: {
        formatter: (v) => Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    legend: {
      position: 'top',
      horizontalAlign: 'left',
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: { formatter: (v) => (v == null ? '—' : Number(v).toLocaleString('en-IN')) },
    },
  }

  const series = [{ name: seriesName, data: thisYear }]
  if (hasLy) series.push({ name: 'Last year', data: lastYear })

  return <Chart options={options} series={series} type="line" height={height} />
}

function MopMixChart({ mopMix, dark, height = 220 }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = ['Mode mix']
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
      stacked: true,
    },
    plotOptions: { bar: { horizontal: false, columnWidth: '55%' } },
    colors: colors.series,
    xaxis: {
      categories: xAxis.categories,
      labels: xAxis.labels,
    },
    yaxis: {
      labels: { style: theme.labelStyle },
    },
    legend: {
      position: 'bottom',
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: theme.tooltipTheme,
      y: { formatter: (v) => Number(v).toLocaleString('en-IN') },
    },
  }
  const series = mopMix.map((m) => ({
    name: m.mop,
    data: [m.count],
  }))
  return <Chart options={options} series={series} type="bar" height={height} />
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
      y: { formatter: (v) => (v == null ? '—' : Number(v).toLocaleString('en-IN')) },
    },
  }
  const series = [{ name: 'Count', data: classMix.map((c) => c.count) }]
  return <Chart options={options} series={series} type="bar" height={height} />
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
  const { kpis, daily_trend, class_mix, mop_mix, lane_throughput } = data
  const topLane = topShare(lane_throughput, 'lane')
  const topClass = topShare(class_mix, 'vehicle_class')
  const topMop = topShare(mop_mix, 'mop')
  const trendGrain = data.trend_grain === 'hour' ? 'hour' : 'day'
  const trendTitle = trendGrain === 'hour' ? 'Hourly traffic' : 'Daily traffic'
  const trendHint =
    trendGrain === 'hour'
      ? `${data.range_label || 'Selected period'} · one point per hour · vs same hours last year`
      : `${data.range_label || 'Selected period'} · one point per day · vs same dates last year`

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi
          label="Period traffic"
          value={formatCount(kpis.traffic_period)}
          hint={data.range_label}
        />
        <Kpi
          label="Top lane"
          value={topLane ? `${topLane.pct}%` : '—'}
          hint={topLane?.name}
        />
        <Kpi
          label="Top vehicle class"
          value={topClass ? `${topClass.pct}%` : '—'}
          hint={topClass?.name}
        />
        <Kpi
          label="Top MOP"
          value={topMop ? `${topMop.pct}%` : '—'}
          hint={topMop?.name}
        />
        <Kpi
          label="vs last year"
          value={formatPct(kpis.vs_ly_traffic_pct)}
          hint="Selected period vs same dates LY"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{trendTitle}</CardTitle>
          <CardDescription>{trendHint}</CardDescription>
        </CardHeader>
        <CardContent>
          {daily_trend.length ? (
            <DailyTrendChart dailyTrend={daily_trend} dark={dark} grain={trendGrain} />
          ) : (
            <p className="text-body text-muted-foreground">
              {trendGrain === 'hour' ? 'No hourly traffic in this period.' : 'No daily traffic in this period.'}
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>MOP Mix</CardTitle>
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
            <CardTitle>Vehicle class mix</CardTitle>
          </CardHeader>
          <CardContent>
            {class_mix.length ? (
              <ClassMixChart classMix={class_mix} dark={dark} />
            ) : (
              <p className="text-body text-muted-foreground">No class data.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Lane throughput</CardTitle>
          </CardHeader>
          <CardContent>
            {lane_throughput.length ? (
              <div className="divide-y divide-border">
                {lane_throughput.map((lane) => (
                  <div
                    key={lane.lane}
                    className="flex items-center justify-between py-2 text-body first:pt-0 last:pb-0"
                  >
                    <span>{lane.lane}</span>
                    <span className="font-medium">{formatCount(lane.count)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-body text-muted-foreground">No lane data.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function LayoutPlaceholder({ title, description }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  )
}

const LAYOUTS = [
  { id: 'overview', label: 'Overview' },
  { id: 'revenue', label: 'Revenue' },
  { id: 'summary', label: 'Summary' },
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
          {layout === 'revenue' && (
            <LayoutPlaceholder
              title="Revenue"
              description="Coming soon — revenue metrics for this plaza will appear here."
            />
          )}
          {layout === 'summary' && (
            <LayoutPlaceholder
              title="Summary"
              description="Coming soon — summary views for this plaza will appear here."
            />
          )}
        </div>
      </div>
    </div>
  )
}
