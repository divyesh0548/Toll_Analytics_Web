import { useMemo, useState } from 'react'
import Chart from 'react-apexcharts'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { categoryTooltipXFormatter, categoryXAxis } from '@/lib/chart-axis'
import { cn } from '@/lib/utils'

export function formatCount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN')
}

export function formatPct(value) {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}%`
}

export function formatGapSec(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Number(value).toFixed(2)}s`
}

export function chartColors(dark) {
  return {
    primary: dark ? '#6fbf7a' : '#2f7a45',
    muted: dark ? '#9ca3af' : '#94a3b8',
    danger: dark ? '#f87171' : '#dc2626',
    series: dark
      ? ['#6fbf7a', '#93c5fd', '#fbbf24', '#f87171', '#c084fc', '#67e8f9', '#fda4af', '#a3e635']
      : ['#2f7a45', '#2563eb', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#e11d48', '#65a30d'],
  }
}

export function chartTheme(dark) {
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

export function baseChartOptions(dark) {
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

export function Kpi({ label, value, hint }) {
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

function ModeToggle({ mode, onChange }) {
  return (
    <div className="flex gap-1">
      {[
        { id: 'count', label: 'Count' },
        { id: 'pct', label: '%' },
      ].map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onChange(item.id)}
          className={cn(
            'rounded-sm px-2 py-1 text-small',
            mode === item.id
              ? 'bg-primary text-primary-foreground'
              : 'bg-secondary text-secondary-foreground',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

function StackedCategoryChart({
  categories,
  series,
  dark,
  height = 280,
  horizontal = false,
  mode = 'count',
  stacked = true,
  chartType = 'bar',
}) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = categories || []
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const displaySeries = series || []

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: chartType,
      stacked: chartType === 'bar' ? stacked : false,
      stackType: mode === 'pct' && chartType === 'bar' ? '100%' : undefined,
      zoom: { enabled: false },
    },
    stroke:
      chartType === 'area' || chartType === 'line'
        ? { width: 2, curve: 'smooth' }
        : { width: 0 },
    fill:
      chartType === 'area'
        ? { type: 'solid', opacity: 0.55 }
        : undefined,
    plotOptions:
      chartType === 'bar'
        ? {
            bar: {
              horizontal,
              columnWidth: '55%',
              barHeight: '70%',
            },
          }
        : undefined,
    colors: colors.series,
    xaxis: {
      categories: xAxis.categories,
      labels: {
        ...xAxis.labels,
        formatter:
          horizontal && mode === 'count'
            ? (v) => Number(v).toLocaleString('en-IN')
            : xAxis.labels?.formatter,
      },
    },
    yaxis: {
      max: mode === 'pct' && chartType === 'bar' && !horizontal ? 100 : undefined,
      labels: {
        formatter: (v) =>
          mode === 'pct'
            ? `${Number(v).toFixed(0)}%`
            : Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    legend: {
      position: 'bottom',
      labels: theme.legend.labels,
    },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: {
        formatter: (v) =>
          mode === 'pct'
            ? `${Number(v).toFixed(1)}%`
            : Number(v).toLocaleString('en-IN'),
      },
    },
  }

  if (!fullCategories.length || !displaySeries.length) {
    return <p className="text-body text-muted-foreground">No data for this chart.</p>
  }

  return (
    <Chart options={options} series={displaySeries} type={chartType} height={height} />
  )
}

function SimpleBarChart({ categories, values, dark, height = 240, horizontal = false }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = categories || []
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
    },
    plotOptions: {
      bar: { horizontal, columnWidth: '55%', barHeight: '70%' },
    },
    colors: [colors.primary],
    xaxis: {
      categories: xAxis.categories,
      labels: {
        ...xAxis.labels,
        formatter: horizontal
          ? (v) => Number(v).toLocaleString('en-IN')
          : xAxis.labels?.formatter,
      },
    },
    yaxis: {
      labels: {
        formatter: (v) => Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    tooltip: {
      theme: theme.tooltipTheme,
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: { formatter: (v) => Number(v).toLocaleString('en-IN') },
    },
  }
  if (!fullCategories.length) {
    return <p className="text-body text-muted-foreground">No data for this chart.</p>
  }
  return (
    <Chart
      options={options}
      series={[{ name: 'Count', data: values || [] }]}
      type="bar"
      height={height}
    />
  )
}

function GapTrendChart({ trend, dark, height = 260 }) {
  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const fullCategories = (trend || []).map((row) => row.label)
  const xAxis = categoryXAxis(fullCategories, theme.labelStyle)
  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'line',
      zoom: { enabled: false },
    },
    stroke: { width: [3, 2], curve: 'smooth' },
    colors: [colors.primary, colors.danger],
    xaxis: {
      categories: xAxis.categories,
      labels: xAxis.labels,
    },
    yaxis: [
      {
        title: { text: 'Avg gap (s)', style: { color: theme.foreColor } },
        labels: {
          formatter: (v) => Number(v).toFixed(1),
          style: theme.labelStyle,
        },
      },
      {
        opposite: true,
        title: { text: 'LT2 count', style: { color: theme.foreColor } },
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
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
    },
  }
  if (!fullCategories.length) {
    return <p className="text-body text-muted-foreground">No gap trend in this period.</p>
  }
  return (
    <Chart
      options={options}
      series={[
        { name: 'Avg gap', data: trend.map((row) => row.avg_gap) },
        { name: 'Gaps < 2s', data: trend.map((row) => row.lt2_count) },
      ]}
      type="line"
      height={height}
    />
  )
}

function MatrixTable({ rowKey, rows, series, valueLabel = 'count' }) {
  const columns = (series || []).map((item) => item.name)
  if (!rows?.length || !columns.length) {
    return <p className="text-body text-muted-foreground">No cross-tab data.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] border-collapse text-left text-small">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="px-2 py-2 font-medium">{rowKey}</th>
            {columns.map((col) => (
              <th key={col} className="px-2 py-2 font-medium">
                {col}
              </th>
            ))}
            <th className="px-2 py-2 font-medium">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((rowLabel, rowIndex) => {
            const cells = (series || []).map((item) => Number(item.data?.[rowIndex]) || 0)
            const total = cells.reduce((sum, n) => sum + n, 0)
            return (
              <tr key={rowLabel} className="border-b border-border/70">
                <td className="px-2 py-2 font-medium">{rowLabel}</td>
                {cells.map((value, index) => (
                  <td key={`${rowLabel}-${columns[index]}`} className="px-2 py-2">
                    {valueLabel === 'gap' ? formatGapSec(value) : formatCount(value)}
                  </td>
                ))}
                <td className="px-2 py-2 font-medium">{formatCount(total)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function LayoutGap({ data, dark }) {
  const gap = data.gap || {}
  const overall = gap.overall || {}
  const byLane = gap.by_lane || []

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Overall avg gap" value={formatGapSec(overall.avg)} hint={data.range_label} />
        <Kpi
          label="Min hourly avg"
          value={formatGapSec(overall.min)}
          hint="Lowest hour-window average"
        />
        <Kpi
          label="Max hourly avg"
          value={formatGapSec(overall.max)}
          hint="Highest hour-window average"
        />
        <Kpi
          label="Gaps < 2s"
          value={formatCount(overall.lt2_count)}
          hint="Flagged headways under 2 seconds"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Average gap by lane</CardTitle>
            <CardDescription>Mean of hourly averages in the selected window</CardDescription>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={byLane.map((row) => row.lane)}
              values={byLane.map((row) => row.avg)}
              dark={dark}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Gaps &lt; 2 seconds by lane</CardTitle>
            <CardDescription>LT2 counts summed over the selected window</CardDescription>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={byLane.map((row) => row.lane)}
              values={byLane.map((row) => row.lt2_count)}
              dark={dark}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Gap trend</CardTitle>
          <CardDescription>
            {data.trend_grain === 'hour'
              ? 'Hourly average gap and LT2 counts'
              : 'Daily average gap and LT2 counts'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <GapTrendChart trend={gap.trend || []} dark={dark} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-lane gap stats</CardTitle>
          <CardDescription>Min/max are extremes of hourly average gaps</CardDescription>
        </CardHeader>
        <CardContent>
          {!byLane.length ? (
            <p className="text-body text-muted-foreground">No gap rows for this period.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[32rem] border-collapse text-left text-small">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Lane</th>
                    <th className="px-2 py-2 font-medium">Avg</th>
                    <th className="px-2 py-2 font-medium">Min</th>
                    <th className="px-2 py-2 font-medium">Max</th>
                    <th className="px-2 py-2 font-medium">Gaps &lt; 2s</th>
                  </tr>
                </thead>
                <tbody>
                  {byLane.map((row) => (
                    <tr key={row.lane} className="border-b border-border/70">
                      <td className="px-2 py-2 font-medium">{row.lane}</td>
                      <td className="px-2 py-2">{formatGapSec(row.avg)}</td>
                      <td className="px-2 py-2">{formatGapSec(row.min)}</td>
                      <td className="px-2 py-2">{formatGapSec(row.max)}</td>
                      <td className="px-2 py-2">{formatCount(row.lt2_count)}</td>
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

export function LayoutClassDistribution({ data, dark }) {
  const block = data.class_distribution || {}
  const totals = block.totals || data.class_mix || []
  const trend = block.trend || { categories: [], series: [] }
  const byLane = block.by_lane || { lanes: [], series: [] }
  const [mode, setMode] = useState('count')
  const top = useMemo(() => {
    if (!totals.length) return null
    const total = totals.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
    const best = totals.reduce((a, b) => ((Number(a.count) || 0) >= (Number(b.count) || 0) ? a : b))
    return {
      name: best.vehicle_class,
      pct: total > 0 ? Math.round((1000 * (Number(best.count) || 0)) / total) / 10 : null,
      total,
    }
  }, [totals])

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label="Period traffic" value={formatCount(top?.total)} hint={data.range_label} />
        <Kpi label="Top class" value={top ? `${top.pct}%` : '—'} hint={top?.name} />
        <Kpi label="Classes" value={formatCount(totals.length)} hint="Distinct vehicle classes" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Class over time</CardTitle>
          <CardDescription>
            {data.trend_grain === 'hour' ? 'Hourly stacked class mix' : 'Daily stacked class mix'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StackedCategoryChart
            categories={trend.categories}
            series={trend.series}
            dark={dark}
            chartType="area"
            height={300}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Vehicle class mix</CardTitle>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={totals.map((row) => row.vehicle_class)}
              values={totals.map((row) => row.count)}
              dark={dark}
              horizontal
              height={Math.max(220, totals.length * 28)}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>Class × lane</CardTitle>
              <CardDescription>Stacked distribution per lane</CardDescription>
            </div>
            <ModeToggle mode={mode} onChange={setMode} />
          </CardHeader>
          <CardContent>
            <StackedCategoryChart
              categories={byLane.lanes}
              series={byLane.series}
              dark={dark}
              mode={mode}
              height={300}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export function LayoutMopDistribution({ data, dark }) {
  const block = data.mop_distribution || {}
  const totals = block.totals || data.mop_mix || []
  const trend = block.trend || { categories: [], series: [] }
  const byLane = block.by_lane || { lanes: [], series: [] }
  const byClass = block.by_class || { classes: [], series: [] }
  const [laneMode, setLaneMode] = useState('count')
  const [classMode, setClassMode] = useState('count')
  const top = useMemo(() => {
    if (!totals.length) return null
    const total = totals.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
    const best = totals.reduce((a, b) => ((Number(a.count) || 0) >= (Number(b.count) || 0) ? a : b))
    return {
      name: best.mop,
      pct: total > 0 ? Math.round((1000 * (Number(best.count) || 0)) / total) / 10 : null,
      total,
    }
  }, [totals])

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Kpi label="Period traffic" value={formatCount(top?.total)} hint={data.range_label} />
        <Kpi label="Top MOP" value={top ? `${top.pct}%` : '—'} hint={top?.name} />
        <Kpi label="MOP types" value={formatCount(totals.length)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>MOP over time</CardTitle>
          <CardDescription>
            {data.trend_grain === 'hour' ? 'Hourly stacked MOP mix' : 'Daily stacked MOP mix'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <StackedCategoryChart
            categories={trend.categories}
            series={trend.series}
            dark={dark}
            chartType="area"
            height={300}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>MOP × lane</CardTitle>
              <CardDescription>Stacked MOP share by lane</CardDescription>
            </div>
            <ModeToggle mode={laneMode} onChange={setLaneMode} />
          </CardHeader>
          <CardContent>
            <StackedCategoryChart
              categories={byLane.lanes}
              series={byLane.series}
              dark={dark}
              mode={laneMode}
              height={300}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle>MOP × class</CardTitle>
              <CardDescription>Stacked MOP share by vehicle class</CardDescription>
            </div>
            <ModeToggle mode={classMode} onChange={setClassMode} />
          </CardHeader>
          <CardContent>
            <StackedCategoryChart
              categories={byClass.classes}
              series={byClass.series}
              dark={dark}
              mode={classMode}
              height={300}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export function LayoutSummary({ data, dark }) {
  const summary = data.summary || {}
  const byMop = summary.by_mop || data.mop_mix || []
  const byClass = summary.by_class || data.class_mix || []
  const byLane = summary.by_lane || data.lane_throughput || []
  const mopXLane = summary.mop_x_lane || { lanes: [], series: [] }
  const mopXClass = summary.mop_x_class || { classes: [], series: [] }
  const classXLane = summary.class_x_lane || { lanes: [], series: [] }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Total by MOP</CardTitle>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={byMop.map((row) => row.mop)}
              values={byMop.map((row) => row.count)}
              dark={dark}
              height={220}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Total by class</CardTitle>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={byClass.map((row) => row.vehicle_class)}
              values={byClass.map((row) => row.count)}
              dark={dark}
              horizontal
              height={220}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Total by lane</CardTitle>
          </CardHeader>
          <CardContent>
            <SimpleBarChart
              categories={byLane.map((row) => row.lane)}
              values={byLane.map((row) => row.count)}
              dark={dark}
              height={220}
            />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>MOP × lane</CardTitle>
            <CardDescription>Cross-join totals for the selected window</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <StackedCategoryChart
              categories={mopXLane.lanes}
              series={mopXLane.series}
              dark={dark}
              height={260}
            />
            <MatrixTable rowKey="Lane" rows={mopXLane.lanes} series={mopXLane.series} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>MOP × class</CardTitle>
            <CardDescription>Payment mode across vehicle classes</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <StackedCategoryChart
              categories={mopXClass.classes}
              series={mopXClass.series}
              dark={dark}
              height={260}
            />
            <MatrixTable rowKey="Class" rows={mopXClass.classes} series={mopXClass.series} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Class × lane</CardTitle>
          <CardDescription>Vehicle class totals across lanes</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <StackedCategoryChart
            categories={classXLane.lanes}
            series={classXLane.series}
            dark={dark}
            height={280}
          />
          <MatrixTable rowKey="Lane" rows={classXLane.lanes} series={classXLane.series} />
        </CardContent>
      </Card>
    </div>
  )
}
