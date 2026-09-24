import Chart from 'react-apexcharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Kpi,
  baseChartOptions,
  chartColors,
  chartTheme,
  formatCount,
  formatMoney,
} from '@/components/plaza/numbers-tabs'
import {
  formatMoneyCompact,
  categoryXAxis,
} from '@/lib/chart-axis'
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
  const revenue = Number(data?.kpis?.revenue_period) || 0
  const trafficLy = classMix.reduce((sum, row) => sum + (Number(row.count_ly) || 0), 0)
  const revenueLy = Number(data?.kpis?.revenue_ly) || 0

  return classMix.map((row) => {
    const count = Number(row.count) || 0
    const share = traffic > 0 ? (count / traffic) * 100 : 0
    const categoryRevenue = traffic > 0 ? revenue * (count / traffic) : 0
    const countLy = Number(row.count_ly) || 0
    const categoryRevenueLy = trafficLy > 0 ? revenueLy * (countLy / trafficLy) : 0
    const revenueYoy =
      categoryRevenueLy > 0
        ? ((categoryRevenue - categoryRevenueLy) / categoryRevenueLy) * 100
        : null

    return {
      vehicle_class: row.vehicle_class,
      count,
      share,
      vs_ly_pct: row.vs_ly_pct,
      revenue: categoryRevenue,
      revenue_share: share,
      revenue_vs_ly_pct: revenueYoy,
    }
  })
}

function monthlyTrendRows(data) {
  const revenueMonthly = data?.revenue?.monthly || []
  const byKey = new Map()
  for (const row of revenueMonthly) {
    const key = `${row.year}-${String(row.month).padStart(2, '0')}`
    byKey.set(key, {
      key,
      label: row.label || key,
      revenue: Number(row.revenue) || 0,
      traffic: 0,
    })
  }
  for (const row of data?.daily_trend || []) {
    if (!row?.date || row.hour != null) continue
    const key = String(row.date).slice(0, 7)
    const existing = byKey.get(key) || {
      key,
      label: key,
      revenue: 0,
      traffic: 0,
    }
    existing.traffic += Number(row.traffic) || 0
    if (!existing.label || existing.label === key) {
      const [y, m] = key.split('-')
      const monthNames = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
      ]
      const mi = Number(m) - 1
      existing.label = Number.isFinite(mi) && monthNames[mi]
        ? `${monthNames[mi]} ${y}`
        : key
    }
    byKey.set(key, existing)
  }
  return [...byKey.values()].sort((a, b) => a.key.localeCompare(b.key))
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
  const categories = rows.map((r) => r.label)
  const xAxis = categoryXAxis(categories, { colors: theme.foreColor, fontSize: '10px' }, 6)
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
      labels: xAxis.labels,
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
        title: { text: 'Revenue (₹)', style: { color: lineColor } },
        labels: {
          style: { colors: lineColor },
          formatter: (v) => formatMoneyCompact(v),
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
            ? formatMoney(v)
            : Number(v).toLocaleString('en-IN'),
      },
    },
  }
  return (
    <Chart
      options={options}
      series={[
        { name: 'Transactions', type: 'column', data: rows.map((r) => r.traffic) },
        { name: 'Revenue', type: 'line', data: rows.map((r) => Math.round(r.revenue)) },
      ]}
      type="line"
      height={320}
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
              <table className="w-full min-w-md border-collapse text-left text-body">
                <thead>
                  <tr className="border-b border-border text-small text-muted-foreground">
                    {columns.map((col) => (
                      <th
                        key={col.key}
                        className={cn(
                          'px-2 py-2 font-medium',
                          col.align === 'right' && 'text-right',
                        )}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={row.vehicle_class} className="border-b border-border/60">
                      {columns.map((col) => (
                        <td
                          key={col.key}
                          className={cn(
                            'px-2 py-2',
                            col.align === 'right' && 'text-right tabular-nums',
                          )}
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
            <CategorySharePie
              rows={rows}
              valueKey={pieValueKey}
              dark={dark}
              valueFormatter={pieValueFormatter}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function OverallTollDashboard({ data, showYoy, dark }) {
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
  const trend = monthlyTrendRows(data)
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
        />
        <Kpi
          label="Total Revenue"
          value={formatMoneyCompact(kpis.revenue_period)}
          hint={data.range_label}
        />
        <Kpi
          label="YoY Revenue Growth"
          value={showYoy ? formatYoyPct(kpis.vs_ly_revenue_pct) : '—'}
          hint={
            showYoy
              ? 'vs same window last year'
              : 'Shown for a single year when prior year has ≥350 days of data'
          }
        />
        <Kpi
          label="Avg. Revenue / Day"
          value={
            avgRevenuePerDay == null ? '—' : formatMoneyCompact(avgRevenuePerDay)
          }
          hint={daySpan ? `${daySpan} days in selection` : 'Selected interval'}
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
          description="Toll collected (₹) per vehicle category (from traffic share)"
          columns={revColumns}
          rows={rows}
          emptyText="No category revenue for this period."
          pieValueKey="revenue"
          pieValueFormatter={(v) => formatMoney(Math.round(v))}
          dark={dark}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Monthly Trend</CardTitle>
          <CardDescription>Transactions and revenue across months in range</CardDescription>
        </CardHeader>
        <CardContent>
          {trend.length ? (
            <MonthlyTrendChart rows={trend} dark={dark} />
          ) : (
            <p className="text-body text-muted-foreground">No monthly trend for this period.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
