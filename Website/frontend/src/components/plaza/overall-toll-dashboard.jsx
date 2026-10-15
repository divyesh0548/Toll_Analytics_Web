import Chart from 'react-apexcharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ChartInset } from '@/components/ui/chart-inset'
import {
  Kpi,
  baseChartOptions,
  chartColors,
  chartTheme,
  formatCount,
  formatMoney,
} from '@/components/plaza/numbers-tabs'
import {
  LAC,
  categoryXAxis,
  dayWeekdayLabel,
  formatMoneyCompact,
  monthAxisGroups,
  spansMultipleMonths,
  trendAxisCategories,
} from '@/lib/chart-axis'

function revenueInLakhs(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.round((n / LAC) * 100) / 100
}
import { cn } from '@/lib/utils'

/** Inclusive days of prior calendar year required before YoY is shown (year interval only). */
export const YOY_MIN_PRIOR_YEAR_DAYS = 350

/**
 * YoY is allowed only for a single full year selection (period=ytd, from===to)
 * when the prior calendar year has at least YOY_MIN_PRIOR_YEAR_DAYS of data.
 */
export function canShowYoy(period, appliedRange, availability) {
  if (period !== 'ytd') return false
  const start = String(appliedRange?.start || '').trim()
  const end = String(appliedRange?.end || '').trim()
  if (!start || !end || start !== end) return false
  const year = Number(start)
  if (!Number.isFinite(year)) return false
  const prior = String(year - 1)
  const dates = availability?.dates || []
  const priorDays = dates.filter((iso) => String(iso).startsWith(prior)).length
  return priorDays >= YOY_MIN_PRIOR_YEAR_DAYS
}

function formatYoyPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}%`
}

function inclusiveDaySpan(startIso, endIso) {
  if (!startIso || !endIso) return 0
  const start = new Date(`${String(startIso).slice(0, 10)}T00:00:00`)
  const end = new Date(`${String(endIso).slice(0, 10)}T00:00:00`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0
  return Math.floor((end.getTime() - start.getTime()) / 86400000) + 1
}

function buildCategoryRows(data) {
  const classMix = data?.class_mix || []
  const traffic = Number(data?.kpis?.traffic_period) || 0

  return classMix.map((row) => {
    const count = Number(row.count) || 0
    const share = traffic > 0 ? (count / traffic) * 100 : 0
    return {
      vehicle_class: row.vehicle_class,
      count,
      share,
      vs_ly_pct: row.vs_ly_pct,
    }
  })
}

function buildRevenueRows(data) {
  const mix = data?.class_revenue || []
  const total = mix.reduce((sum, row) => sum + (Number(row.revenue) || 0), 0)
  if (!mix.length || total === 0) return []
  return mix.map((row) => {
    const revenue = Number(row.revenue) || 0
    return {
      vehicle_class: row.vehicle_class,
      revenue,
      revenue_share: total > 0 ? (revenue / total) * 100 : 0,
      revenue_vs_ly_pct: row.vs_ly_pct,
    }
  })
}

function comparisonRows(data) {
  const byClass = new Map()
  for (const row of data?.class_mix || []) {
    const name = String(row.vehicle_class || '').trim()
    if (!name) continue
    byClass.set(name, {
      vehicle_class: name,
      count: Number(row.count) || 0,
      revenue: 0,
    })
  }
  for (const row of data?.class_revenue || []) {
    const name = String(row.vehicle_class || '').trim()
    if (!name) continue
    const existing = byClass.get(name) || {
      vehicle_class: name,
      count: 0,
      revenue: 0,
    }
    existing.revenue = Number(row.revenue) || 0
    byClass.set(name, existing)
  }
  return [...byClass.values()]
    .filter((row) => row.count > 0 || row.revenue > 0)
    .sort((a, b) => b.count - a.count || b.revenue - a.revenue)
}

/** Keep chart readable: when many points, keep every Nth (always include last). */
const TREND_MAX_POINTS = 16

function downsampleTrendRows(rows, maxPoints = TREND_MAX_POINTS) {
  if (!rows?.length || rows.length <= maxPoints) return rows || []
  const step = Math.ceil(rows.length / maxPoints)
  const out = []
  for (let i = 0; i < rows.length; i += step) {
    out.push(rows[i])
  }
  const last = rows[rows.length - 1]
  if (out[out.length - 1]?.key !== last.key) {
    out.push(last)
  }
  return out
}

function dailyTrendRows(data) {
  const revenueDaily = data?.revenue?.daily || []
  const rows = revenueDaily
    .map((row) => {
      const date = String(row.date || '').slice(0, 10)
      const label =
        date && /^\d{4}-\d{2}-\d{2}$/.test(date)
          ? dayWeekdayLabel(date)
          : row.label || date
      return {
        key: date || label,
        label,
        revenue: Number(row.revenue) || 0,
        traffic: Number(row.txn_count) || 0,
      }
    })
    .sort((a, b) => String(a.key).localeCompare(String(b.key)))
  return downsampleTrendRows(rows)
}

function monthlyTrendRows(data) {
  const revenueMonthly = data?.revenue?.monthly || []
  return revenueMonthly
    .map((row) => {
      const key = `${row.year}-${String(row.month).padStart(2, '0')}`
      return {
        key,
        label: row.label || key,
        revenue: Number(row.revenue) || 0,
        traffic: Number(row.txn_count) || 0,
      }
    })
    .sort((a, b) => a.key.localeCompare(b.key))
}

function yearlyTrendRows(data) {
  const revenueMonthly = data?.revenue?.monthly || []
  const byYear = new Map()
  for (const row of revenueMonthly) {
    const year = Number(row.year)
    if (!Number.isFinite(year)) continue
    const existing = byYear.get(year) || { key: String(year), label: String(year), revenue: 0, traffic: 0 }
    existing.revenue += Number(row.revenue) || 0
    existing.traffic += Number(row.txn_count) || 0
    byYear.set(year, existing)
  }
  return [...byYear.values()].sort((a, b) => Number(a.key) - Number(b.key))
}

function trendRowsForPeriod(period, data) {
  const p = String(period || 'mtd').toLowerCase()
  if (p === 'day') return dailyTrendRows(data)
  if (p === 'ytd') return yearlyTrendRows(data)
  return monthlyTrendRows(data)
}

function trendCopy(period) {
  const p = String(period || 'mtd').toLowerCase()
  if (p === 'day') {
    return {
      title: 'Daily Trend',
      description: 'Transactions and revenue by day in the selected range',
      empty: 'No daily trend for this period.',
    }
  }
  if (p === 'ytd') {
    return {
      title: 'Yearly Trend',
      description: 'Transactions and revenue by year in the selected range',
      empty: 'No yearly trend for this period.',
    }
  }
  return {
    title: 'Monthly Trend',
    description: 'Transactions and revenue across months in range',
    empty: 'No monthly trend for this period.',
  }
}

function categoryColor(dark, index) {
  const series = chartColors(dark).series
  return series[index % series.length]
}

function CategorySharePie({ rows, valueKey, dark, valueFormatter }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const labels = rows.map((r) => r.vehicle_class)
  const series = rows.map((r) => {
    const n = Number(r[valueKey]) || 0
    return valueKey === 'revenue' ? Math.round(n) : n
  })
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'donut',
    },
    labels,
    colors: colors.series,
    legend: { show: false },
    dataLabels: {
      enabled: true,
      formatter: (val) => `${Math.round(val)}%`,
      style: { fontSize: '11px' },
    },
    plotOptions: {
      pie: {
        donut: {
          size: '58%',
          labels: {
            show: true,
            total: {
              show: true,
              label: 'Total',
              formatter: () => {
                const total = series.reduce((sum, v) => sum + v, 0)
                return valueFormatter ? valueFormatter(total) : formatCount(total)
              },
            },
          },
        },
      },
    },
    tooltip: {
      theme: theme.tooltipTheme,
      y: {
        formatter: (v) => (valueFormatter ? valueFormatter(v) : formatCount(v)),
      },
    },
  }
  return <Chart options={options} series={series} type="donut" height={280} />
}

function MonthlyTrendChart({ rows, dark }) {
  const theme = chartTheme(dark)
  const isoDates = rows.map((r) => String(r.key || '').slice(0, 10))
  const hasDailyIso =
    isoDates.length === rows.length &&
    isoDates.every((iso) => /^\d{4}-\d{2}-\d{2}$/.test(iso))
  const multiMonth = hasDailyIso && spansMultipleMonths(isoDates)
  const categories = trendAxisCategories(
    hasDailyIso ? isoDates : [],
    rows.map((r) => r.label),
  )
  // Show a label on every bar (day / month / year) — do not thin the axis.
  const xAxis = categoryXAxis(
    categories,
    { colors: theme.foreColor, fontSize: '10px' },
    Math.max(categories.length, 1),
  )
  const monthGroups = multiMonth
    ? monthAxisGroups(isoDates, { colors: theme.foreColor })
    : undefined
  // Distinct hues: cool blue bars (traffic) vs warm amber line (revenue)
  const barColor = dark ? '#60a5fa' : '#1d4ed8'
  const lineColor = dark ? '#fbbf24' : '#c2410c'
  const options = {
    ...baseChartOptions(dark),
    stroke: { width: [0, 3], curve: 'smooth' },
    colors: [barColor, lineColor],
    fill: {
      opacity: [0.85, 1],
    },
    markers: {
      size: [0, 4],
      colors: [lineColor],
      strokeColors: dark ? '#1f2937' : '#fff',
      strokeWidth: 2,
    },
    plotOptions: {
      bar: { columnWidth: '55%', borderRadius: 2 },
    },
    xaxis: {
      categories: xAxis.categories,
      labels: {
        ...xAxis.labels,
        hideOverlappingLabels: false,
        showDuplicates: true,
      },
      ...(monthGroups ? { group: monthGroups } : {}),
    },
    yaxis: [
      {
        title: { text: 'Transactions', style: { color: barColor } },
        labels: {
          style: { colors: barColor },
          formatter: (v) => Number(v).toLocaleString('en-IN'),
        },
      },
      {
        opposite: true,
        title: { text: 'Revenue (₹ Lakh)', style: { color: lineColor } },
        labels: {
          style: { colors: lineColor },
          formatter: (v) =>
            `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Lakh`,
        },
      },
    ],
    legend: {
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: dark ? 'dark' : 'light',
      shared: true,
      y: {
        formatter: (v, opts) =>
          opts.seriesIndex === 1
            ? `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Lakh`
            : Number(v).toLocaleString('en-IN'),
      },
    },
  }
  return (
    <Chart
      options={options}
      series={[
        { name: 'Transactions', type: 'column', data: rows.map((r) => r.traffic) },
        { name: 'Revenue', type: 'line', data: rows.map((r) => revenueInLakhs(r.revenue)) },
      ]}
      type="line"
      height={320}
    />
  )
}

function CategoryComparisonChart({ rows, dark }) {
  const theme = chartTheme(dark)
  const categories = rows.map((r) => r.vehicle_class)
  const xAxis = categoryXAxis(categories, { colors: theme.foreColor, fontSize: '11px' }, 16)
  const countColor = dark ? '#60a5fa' : '#1d4ed8'
  const revenueColor = dark ? '#fbbf24' : '#c2410c'
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
    },
    colors: [countColor, revenueColor],
    plotOptions: {
      bar: { horizontal: false, columnWidth: '52%', borderRadius: 2 },
    },
    dataLabels: { enabled: false },
    stroke: { show: true, width: 2, colors: ['transparent'] },
    xaxis: {
      categories: xAxis.categories,
      labels: xAxis.labels,
    },
    yaxis: [
      {
        seriesName: 'Transactions',
        title: { text: 'Transactions', style: { color: countColor } },
        labels: {
          style: { colors: countColor },
          formatter: (v) => Number(v).toLocaleString('en-IN'),
        },
      },
      {
        seriesName: 'Revenue',
        opposite: true,
        title: { text: 'Revenue (₹ Lakh)', style: { color: revenueColor } },
        labels: {
          style: { colors: revenueColor },
          formatter: (v) =>
            `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Lakh`,
        },
      },
    ],
    legend: {
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: dark ? 'dark' : 'light',
      shared: true,
      intersect: false,
      y: {
        formatter: (v, opts) =>
          opts.seriesIndex === 1
            ? `${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Lakh`
            : Number(v).toLocaleString('en-IN'),
      },
    },
  }
  return (
    <Chart
      options={options}
      series={[
        { name: 'Transactions', data: rows.map((r) => r.count) },
        { name: 'Revenue', data: rows.map((r) => revenueInLakhs(r.revenue)) },
      ]}
      type="bar"
      height={340}
    />
  )
}

function CategoryPanel({
  title,
  description,
  columns,
  rows,
  emptyText,
  pieValueKey,
  pieValueFormatter,
  dark,
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-body text-muted-foreground">{emptyText}</p>
        ) : (
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto">
              <table className="dashboard-table min-w-md">
                <thead>
                  <tr>
                    {columns.map((col) => (
                      <th
                        key={col.key}
                        className={cn(col.align === 'right' && 'num')}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={row.vehicle_class}>
                      {columns.map((col) => (
                        <td
                          key={col.key}
                          className={cn(col.align === 'right' && 'num')}
                        >
                          {col.key === 'class' ? (
                            <span className="inline-flex items-center gap-2 font-medium">
                              <span
                                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                                style={{ backgroundColor: categoryColor(dark, index) }}
                                aria-hidden
                              />
                              <span style={{ color: categoryColor(dark, index) }}>
                                {col.render(row)}
                              </span>
                            </span>
                          ) : (
                            col.render(row)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ChartInset>
              <CategorySharePie
                rows={rows}
                valueKey={pieValueKey}
                dark={dark}
                valueFormatter={pieValueFormatter}
              />
            </ChartInset>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function OverallTollDashboard({ data, showYoy, dark, period = 'mtd' }) {
  if (!data?.has_data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>No data found</CardTitle>
          <CardDescription>
            Try a different plaza, year or month.
          </CardDescription>
        </CardHeader>
      </Card>
    )
  }

  const kpis = data.kpis || {}
  const rows = buildCategoryRows(data)
  const revenueRows = buildRevenueRows(data)
  const trend = trendRowsForPeriod(period, data)
  const trendMeta = trendCopy(period)
  const comparison = comparisonRows(data)
  const daySpan = inclusiveDaySpan(data.start_date, data.end_date)
  const avgRevenuePerDay =
    daySpan > 0 && kpis.revenue_period != null
      ? Number(kpis.revenue_period) / daySpan
      : null

  const txnColumns = [
    {
      key: 'class',
      label: 'Vehicle Category',
      render: (row) => row.vehicle_class,
    },
    {
      key: 'count',
      label: 'Transactions',
      align: 'right',
      render: (row) => formatCount(row.count),
    },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      render: (row) => `${row.share.toFixed(1)}%`,
    },
  ]
  if (showYoy) {
    txnColumns.push({
      key: 'yoy',
      label: 'YoY',
      align: 'right',
      render: (row) => formatYoyPct(row.vs_ly_pct),
    })
  }

  const revColumns = [
    {
      key: 'class',
      label: 'Vehicle Category',
      render: (row) => row.vehicle_class,
    },
    {
      key: 'amount',
      label: 'Amount (₹)',
      align: 'right',
      render: (row) => formatMoney(Math.round(row.revenue)),
    },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      render: (row) => `${row.revenue_share.toFixed(1)}%`,
    },
  ]
  if (showYoy) {
    revColumns.push({
      key: 'yoy',
      label: 'YoY',
      align: 'right',
      render: (row) => formatYoyPct(row.revenue_vs_ly_pct),
    })
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-subheader">{data.range_label || 'Selected period'}</h2>
        <p className="text-small text-muted-foreground">ETC transaction report</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Total Transactions"
          value={formatCount(kpis.traffic_period)}
          hint={data.range_label}
          accent="traffic"
        />
        <Kpi
          label="Total Revenue"
          value={formatMoneyCompact(kpis.revenue_period)}
          hint={data.range_label}
          accent="revenue"
        />
        <Kpi
          label="YoY Revenue Growth"
          value={showYoy ? formatYoyPct(kpis.vs_ly_revenue_pct) : '—'}
          hint={
            showYoy
              ? 'vs same window last year'
              : 'Shown for a single year when prior year has ≥350 days of data'
          }
          accent="revenue"
        />
        <Kpi
          label="Avg. Revenue / Day"
          value={
            avgRevenuePerDay == null ? '—' : formatMoneyCompact(avgRevenuePerDay)
          }
          hint={daySpan ? `${daySpan} days in selection` : 'Selected interval'}
          accent="revenue"
        />
      </div>

      <div className="space-y-4">
        <CategoryPanel
          title="Transaction Count"
          description="Volume of transactions by vehicle category"
          columns={txnColumns}
          rows={rows}
          emptyText="No category traffic for this period."
          pieValueKey="count"
          pieValueFormatter={(v) => formatCount(v)}
          dark={dark}
        />
        <CategoryPanel
          title="Revenue Collected"
          description="Toll collected (₹) per vehicle category"
          columns={revColumns}
          rows={revenueRows}
          emptyText="No category revenue for this period."
          pieValueKey="revenue"
          pieValueFormatter={(v) => formatMoney(Math.round(v))}
          dark={dark}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Category Comparison</CardTitle>
          <CardDescription>Side-by-side count and revenue per category</CardDescription>
        </CardHeader>
        <CardContent>
          {comparison.length ? (
            <ChartInset>
              <CategoryComparisonChart rows={comparison} dark={dark} />
            </ChartInset>
          ) : (
            <p className="text-body text-muted-foreground">
              No category comparison for this period.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-subheader text-muted-foreground">
            {trendMeta.title}
          </CardTitle>
          <CardDescription>{trendMeta.description}</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.length ? (
            <ChartInset>
              <MonthlyTrendChart rows={trend} dark={dark} />
            </ChartInset>
          ) : (
            <p className="text-body text-muted-foreground">{trendMeta.empty}</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
