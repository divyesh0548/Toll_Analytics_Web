import { useMemo, useRef, useState } from 'react'
import Chart from 'react-apexcharts'
import { CalendarDays, ChevronLeft, ChevronRight, Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { useAuth } from '@/components/auth-provider'
import { useTheme } from '@/components/theme-provider'
import { useToast } from '@/components/toast-provider'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  baseChartOptions,
  chartColors,
  chartTheme,
} from '@/components/plaza/numbers-tabs'
import {
  createPlazaCalendarEvent,
  deletePlazaCalendarEvent,
  updatePlazaCalendarEvent,
  uploadPlazaCalendarEvents,
} from '@/lib/api'
import { categoryTooltipXFormatter, categoryXAxis } from '@/lib/chart-axis'
import { cn } from '@/lib/utils'

export const EVENT_TYPE_OPTIONS = [
  { value: 'national_holiday', label: 'National holiday', short: 'National' },
  { value: 'regional_holiday', label: 'Regional holiday', short: 'Regional' },
  { value: 'bank_holiday', label: 'Bank holiday', short: 'Bank' },
  { value: 'govt_holiday', label: 'Govt holiday', short: 'Govt' },
  { value: 'election_day', label: 'Election day', short: 'Election' },
  { value: 'mela_window', label: 'Mela window', short: 'Mela' },
]

const EVENT_TYPE_LABEL = Object.fromEntries(
  EVENT_TYPE_OPTIONS.map((opt) => [opt.value, opt.label]),
)

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const emptyForm = () => ({
  label: '',
  event_type: 'national_holiday',
  start_date: '',
  end_date: '',
})

export function monthBounds(yearMonth) {
  const [y, m] = String(yearMonth || '').split('-').map(Number)
  if (!y || !m) return { start: '', end: '' }
  const lastDay = new Date(y, m, 0).getDate()
  return {
    start: `${y}-${String(m).padStart(2, '0')}-01`,
    end: `${y}-${String(m).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`,
  }
}

export function defaultTrafficMonth() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

function shiftMonth(yearMonth, delta) {
  const [y, m] = String(yearMonth).split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function eventsForDay(events, dayIso) {
  return events.filter((ev) => ev.start_date <= dayIso && ev.end_date >= dayIso)
}

function buildCalendarCells(yearMonth) {
  const [y, m] = String(yearMonth).split('-').map(Number)
  const first = new Date(y, m - 1, 1)
  const startPad = (first.getDay() + 6) % 7
  const daysInMonth = new Date(y, m, 0).getDate()
  const cells = []
  for (let i = 0; i < startPad; i += 1) cells.push(null)
  for (let day = 1; day <= daysInMonth; day += 1) {
    cells.push(new Date(y, m - 1, day))
  }
  while (cells.length % 7 !== 0) cells.push(null)
  return cells
}

function trafficByDateMap(dailyTrend) {
  const map = new Map()
  for (const point of dailyTrend || []) {
    const key = point.date
    if (!key) continue
    const value = Number(point.traffic) || 0
    map.set(key, (map.get(key) || 0) + value)
  }
  return map
}

function monthSeries(dailyTrend, yearMonth) {
  const [y, m] = String(yearMonth).split('-').map(Number)
  const daysInMonth = new Date(y, m, 0).getDate()
  const byDate = trafficByDateMap(dailyTrend)
  const categories = []
  const data = []
  const dates = []
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${y}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    categories.push(String(day))
    dates.push(iso)
    data.push(byDate.has(iso) ? byDate.get(iso) : null)
  }
  return { categories, data, dates }
}

function eventRangeAnnotations(visibleEvents, dates, colors) {
  const dayIndex = new Map(dates.map((iso, idx) => [iso, idx]))
  const ranges = []
  for (const ev of visibleEvents || []) {
    const start = new Date(`${ev.start_date}T00:00:00`)
    const end = new Date(`${ev.end_date}T00:00:00`)
    let firstIdx = null
    let lastIdx = null
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const idx = dayIndex.get(isoDate(d))
      if (idx == null) continue
      if (firstIdx == null) firstIdx = idx
      lastIdx = idx
    }
    if (firstIdx == null || lastIdx == null) continue
    const fill =
      ev.event_type === 'mela_window' ? '#d97706' : colors.danger
    ranges.push({
      x: dates[firstIdx]
        ? String(new Date(`${dates[firstIdx]}T00:00:00`).getDate())
        : String(firstIdx + 1),
      x2: dates[lastIdx]
        ? String(new Date(`${dates[lastIdx]}T00:00:00`).getDate())
        : String(lastIdx + 1),
      fillColor: fill,
      opacity: 0.16,
      borderColor: fill,
      strokeDashArray: 0,
      label: {
        text: ev.label || EVENT_TYPE_LABEL[ev.event_type] || 'Event',
        orientation: 'horizontal',
        position: 'top',
        offsetY: -4,
        borderColor: fill,
        borderWidth: 1,
        borderRadius: 2,
        textAnchor: 'middle',
        style: {
          color: dark ? '#fafafa' : '#ffffff',
          background: fill,
          fontSize: '11px',
          fontWeight: 600,
          padding: {
            left: 6,
            right: 6,
            top: 2,
            bottom: 2,
          },
        },
      },
    })
  }
  return ranges.slice(0, 20)
}

function highlightMinMaxColors(values, baseColor, accentMin, accentMax) {
  if (!values.length) return []
  let minIdx = 0
  let maxIdx = 0
  for (let i = 1; i < values.length; i += 1) {
    if (values[i] < values[minIdx]) minIdx = i
    if (values[i] > values[maxIdx]) maxIdx = i
  }
  return values.map((_, idx) => {
    if (idx === maxIdx) return accentMax
    if (idx === minIdx) return accentMin
    return baseColor
  })
}

function MonthTrafficChart({ dailyTrend, monthValue, visibleEvents, dark }) {
  const series = useMemo(
    () => monthSeries(dailyTrend, monthValue),
    [dailyTrend, monthValue],
  )
  if (!series.categories.length) {
    return (
      <p className="text-body text-muted-foreground">
        No traffic counts available for this month.
      </p>
    )
  }

  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const annotations = {
    xaxis: eventRangeAnnotations(visibleEvents, series.dates, {
      danger: colors.danger,
      foreground: dark ? '#e5e5e5' : '#171717',
    }, dark),
  }

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'line',
      zoom: { enabled: false },
    },
    stroke: { width: 3, curve: 'smooth' },
    markers: { size: 3 },
    colors: [colors.primary],
    xaxis: {
      categories: series.categories,
      title: { text: 'Date of month', style: theme.labelStyle },
      labels: {
        rotate: 0,
        rotateAlways: false,
        hideOverlappingLabels: false,
        trim: false,
        style: theme.labelStyle,
      },
    },
    yaxis: {
      labels: {
        formatter: (v) => Number(v).toLocaleString('en-IN'),
        style: theme.labelStyle,
      },
    },
    annotations,
    tooltip: {
      theme: theme.tooltipTheme,
      x: {
        formatter: (_val, opts) => {
          const idx = opts?.dataPointIndex
          const day = series.categories[idx]
          const iso = series.dates[idx]
          return iso ? `${day} (${iso})` : String(day)
        },
      },
      y: { formatter: (v) => (v == null ? '—' : Number(v).toLocaleString('en-IN')) },
    },
  }

  return (
    <Chart
      options={options}
      series={[{ name: 'Daily traffic', data: series.data }]}
      type="line"
      height={300}
    />
  )
}

function AvgBarChart({
  title,
  subtitle,
  categories,
  values,
  dark,
  emptyText,
  rotateLabels = false,
}) {
  if (!categories?.length || !values?.length) {
    return <p className="text-body text-muted-foreground">{emptyText}</p>
  }

  const colors = chartColors(dark)
  const theme = chartTheme(dark)
  const barColors = highlightMinMaxColors(
    values,
    colors.primary,
    colors.muted || '#94a3b8',
    colors.danger,
  )

  const options = {
    ...baseChartOptions(dark),
    chart: {
      ...baseChartOptions(dark).chart,
      type: 'bar',
      zoom: { enabled: false },
    },
    plotOptions: {
      bar: {
        distributed: true,
        borderRadius: 2,
        columnWidth: '60%',
      },
    },
    legend: { show: false },
    colors: barColors,
    xaxis: {
      categories,
      labels: {
        rotate: rotateLabels ? -45 : 0,
        rotateAlways: Boolean(rotateLabels),
        hideOverlappingLabels: false,
        trim: false,
        minHeight: rotateLabels ? 56 : undefined,
        style: theme.labelStyle,
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
      x: { formatter: categoryTooltipXFormatter(categories) },
      y: {
        formatter: (v) =>
          v == null ? '—' : `${Number(v).toLocaleString('en-IN')} (average)`,
      },
    },
    dataLabels: { enabled: false },
  }

  return (
    <div>
      <div className="mb-2">
        <h3 className="text-body font-medium">{title}</h3>
        <p className="text-small text-muted-foreground">{subtitle}</p>
      </div>
      <Chart
        options={options}
        series={[{ name: 'Average traffic', data: values }]}
        type="bar"
        height={rotateLabels ? 280 : 240}
      />
      <p className="mt-1 text-small text-muted-foreground">
        Highlighted: peak (max) and trough (min) average window.
      </p>
    </div>
  )
}

function EventFilters({ enabledTypes, excludeMela, onToggleType, onToggleExcludeMela }) {
  return (
    <div className="space-y-2">
      <span className="text-small font-medium text-muted-foreground">Filter events</span>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {EVENT_TYPE_OPTIONS.map((opt) => {
          const checked =
            enabledTypes.has(opt.value) && !(excludeMela && opt.value === 'mela_window')
          const disabled = excludeMela && opt.value === 'mela_window'
          return (
            <label
              key={opt.value}
              className={cn(
                'inline-flex items-center gap-2 text-body',
                disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
              )}
            >
              <input
                type="checkbox"
                className="h-4 w-4 rounded-sm border-border accent-primary"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggleType(opt.value)}
              />
              <span>{opt.label}</span>
            </label>
          )
        })}
        <label className="inline-flex items-center gap-2 text-body cursor-pointer">
          <input
            type="checkbox"
            className="h-4 w-4 rounded-sm border-border accent-primary"
            checked={excludeMela}
            onChange={onToggleExcludeMela}
          />
          <span>Exclude mela window</span>
        </label>
      </div>
    </div>
  )
}

function CalendarGrid({
  monthValue,
  visibleEvents,
  trafficByDate,
  showTraffic = false,
  loading = false,
}) {
  const cells = useMemo(() => buildCalendarCells(monthValue), [monthValue])
  return (
    <div>
      <div className="grid grid-cols-7 gap-1 text-center text-small text-muted-foreground">
        {WEEKDAYS.map((d) => (
          <div key={d} className="py-1 font-medium">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, idx) => {
          if (!day) {
            return <div key={`empty-${idx}`} className="min-h-[4.5rem] rounded-sm bg-muted/30" />
          }
          const dayIso = isoDate(day)
          const dayEvents = eventsForDay(visibleEvents, dayIso)
          const count = trafficByDate?.get(dayIso)
          return (
            <div
              key={dayIso}
              className={cn(
                'min-h-[4.5rem] rounded-sm border border-border p-1',
                dayEvents.length ? 'bg-primary/5' : '',
              )}
            >
              <div className="flex items-start justify-between gap-1">
                <div className="text-small font-medium">{day.getDate()}</div>
                {showTraffic ? (
                  <div className="text-[10px] font-medium text-muted-foreground">
                    {count == null
                      ? loading
                        ? '…'
                        : '—'
                      : Number(count).toLocaleString('en-IN')}
                  </div>
                ) : null}
              </div>
              <div className="mt-0.5 space-y-0.5">
                {dayEvents.slice(0, showTraffic ? 1 : 2).map((ev) => (
                  <div
                    key={`${ev.id}-${dayIso}`}
                    className="truncate rounded-sm bg-primary/10 px-1 text-[10px] leading-4 text-foreground"
                    title={ev.label}
                  >
                    {ev.label}
                  </div>
                ))}
                {dayEvents.length > (showTraffic ? 1 : 2) ? (
                  <div className="text-[10px] text-muted-foreground">
                    +{dayEvents.length - (showTraffic ? 1 : 2)} more
                  </div>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function TrafficStudyPanel({
  plazaIdentifier,
  events = [],
  loading = false,
  error = '',
  monthValue,
  onMonthChange,
  dailyTrend = [],
  hourlyAvgProfile = [],
  weekdayAvgProfile = [],
  trafficLoading = false,
  onRefresh,
}) {
  const { canWrite } = useAuth()
  const { theme } = useTheme()
  const dark = theme === 'dark'
  const { showToast } = useToast()
  const fileRef = useRef(null)

  const [studyTab, setStudyTab] = useState('peaks')
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [enabledTypes, setEnabledTypes] = useState(
    () => new Set(EVENT_TYPE_OPTIONS.map((o) => o.value)),
  )
  const [excludeMela, setExcludeMela] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [uploading, setUploading] = useState(false)

  const visibleEvents = useMemo(() => {
    return (events || []).filter((ev) => {
      if (excludeMela && ev.event_type === 'mela_window') return false
      return enabledTypes.has(ev.event_type)
    })
  }, [events, enabledTypes, excludeMela])

  const [year, month] = String(monthValue || '').split('-').map(Number)
  const monthLabel = year && month ? `${MONTH_NAMES[month - 1]} ${year}` : monthValue
  const trafficByDate = useMemo(() => trafficByDateMap(dailyTrend), [dailyTrend])

  const hourlyCategories = useMemo(
    () => (hourlyAvgProfile || []).map((r) => r.label || r.hour),
    [hourlyAvgProfile],
  )
  const hourlyValues = useMemo(
    () => (hourlyAvgProfile || []).map((r) => Number(r.avg_traffic) || 0),
    [hourlyAvgProfile],
  )
  const weekdayCategories = useMemo(
    () => (weekdayAvgProfile || []).map((r) => r.label || r.weekday),
    [weekdayAvgProfile],
  )
  const weekdayValues = useMemo(
    () => (weekdayAvgProfile || []).map((r) => Number(r.avg_traffic) || 0),
    [weekdayAvgProfile],
  )

  function toggleType(value) {
    setEnabledTypes((prev) => {
      const next = new Set(prev)
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return next
    })
  }

  function openCreate() {
    const bounds = monthBounds(monthValue)
    setEditing(null)
    setForm({
      ...emptyForm(),
      start_date: bounds.start,
      end_date: bounds.start,
    })
    setFormError('')
    setFormOpen(true)
  }

  function openEdit(event) {
    setEditing(event)
    setForm({
      label: event.label || '',
      event_type: event.event_type || 'national_holiday',
      start_date: event.start_date || '',
      end_date: event.end_date || event.start_date || '',
    })
    setFormError('')
    setFormOpen(true)
  }

  async function handleSaveEvent(e) {
    e.preventDefault()
    setFormError('')
    if (!form.label.trim()) {
      setFormError('Label is required.')
      return
    }
    if (!form.start_date) {
      setFormError('Start date is required.')
      return
    }
    const payload = {
      label: form.label.trim(),
      event_type: form.event_type,
      start_date: form.start_date,
      end_date: form.end_date || form.start_date,
    }
    setSaving(true)
    try {
      if (editing) {
        await updatePlazaCalendarEvent(plazaIdentifier, editing.id, payload)
        showToast('Event updated')
      } else {
        await createPlazaCalendarEvent(plazaIdentifier, payload)
        showToast('Event created')
      }
      setFormOpen(false)
      onRefresh?.()
    } catch (err) {
      setFormError(err.message || 'Could not save event')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(event) {
    if (!window.confirm(`Delete “${event.label}”?`)) return
    try {
      await deletePlazaCalendarEvent(plazaIdentifier, event.id)
      showToast('Event deleted')
      onRefresh?.()
    } catch (err) {
      showToast(err.message || 'Could not delete event', 'error')
    }
  }

  async function handleUpload(file) {
    if (!file) return
    setUploading(true)
    try {
      const result = await uploadPlazaCalendarEvents(plazaIdentifier, file)
      const errCount = result.errors?.length || 0
      showToast(
        `Upload complete: ${result.created} created, ${result.skipped} skipped` +
          (errCount ? `, ${errCount} row error(s)` : ''),
        errCount ? 'warning' : 'success',
      )
      onRefresh?.()
    } catch (err) {
      showToast(err.message || 'Upload failed', 'error')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-header">Traffic study</h2>
          <p className="text-body text-muted-foreground">
            Monthly traffic profile with event overlays for {monthLabel}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => onMonthChange?.(shiftMonth(monthValue, -1))}
              aria-label="Previous month"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-[9rem] text-center text-body font-medium">{monthLabel}</span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => onMonthChange?.(shiftMonth(monthValue, 1))}
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          {studyTab === 'events' && canWrite ? (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                className="hidden"
                onChange={(e) => handleUpload(e.target.files?.[0])}
              />
              <Button
                type="button"
                variant="outline"
                disabled={uploading}
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="h-4 w-4" />
                {uploading ? 'Uploading…' : 'Upload'}
              </Button>
              <Button type="button" onClick={openCreate}>
                <Plus className="h-4 w-4" />
                Add event
              </Button>
            </>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-border pb-2">
        {[
          { id: 'peaks', label: 'Peaks & profiles' },
          { id: 'events', label: 'Events calendar' },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setStudyTab(tab.id)}
            className={cn(
              'rounded-sm px-3 py-1.5 text-body',
              studyTab === tab.id
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <EventFilters
        enabledTypes={enabledTypes}
        excludeMela={excludeMela}
        onToggleType={toggleType}
        onToggleExcludeMela={() => setExcludeMela((v) => !v)}
      />

      {error ? (
        <Card>
          <CardHeader>
            <CardTitle>Calendar unavailable</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {studyTab === 'peaks' ? (
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Monthly traffic</CardTitle>
                <CardDescription>
                  All dates on the X-axis · shaded bands mark selected event windows
                  {trafficLoading ? ' · loading…' : ''}
                </CardDescription>
              </div>
              <Button type="button" variant="outline" onClick={() => setCalendarOpen(true)}>
                <CalendarDays className="h-4 w-4" />
                Calendar
              </Button>
            </CardHeader>
            <CardContent>
              <MonthTrafficChart
                dailyTrend={dailyTrend}
                monthValue={monthValue}
                visibleEvents={visibleEvents}
                dark={dark}
              />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardContent className="pt-6">
                <AvgBarChart
                  title="Hourly profile · peak hour"
                  subtitle="Average of each one-hour window across all days in this month"
                  categories={hourlyCategories}
                  values={hourlyValues}
                  dark={dark}
                  emptyText="No hourly averages for this month."
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <AvgBarChart
                  title="Day-of-week index"
                  subtitle="Average daily traffic by weekday across this month"
                  categories={weekdayCategories}
                  values={weekdayValues}
                  dark={dark}
                  emptyText="No weekday averages for this month."
                />
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Event-tagged calendar</CardTitle>
              <CardDescription>
                {loading ? 'Loading events…' : `${visibleEvents.length} event(s) in view`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CalendarGrid monthValue={monthValue} visibleEvents={visibleEvents} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Events</CardTitle>
              <CardDescription>
                Upload .xlsx / .csv with columns start_date, end_date, label, event_type.
              </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full min-w-[40rem] border-collapse text-left text-body">
                <thead>
                  <tr className="border-b border-border text-small text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Label</th>
                    <th className="px-2 py-2 font-medium">Type</th>
                    <th className="px-2 py-2 font-medium">Start</th>
                    <th className="px-2 py-2 font-medium">End</th>
                    <th className="px-2 py-2 font-medium">Source</th>
                    {canWrite ? <th className="px-2 py-2 font-medium">Actions</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {visibleEvents.length === 0 ? (
                    <tr>
                      <td
                        colSpan={canWrite ? 6 : 5}
                        className="px-2 py-6 text-center text-muted-foreground"
                      >
                        {loading ? 'Loading…' : 'No events for this month.'}
                      </td>
                    </tr>
                  ) : (
                    visibleEvents.map((ev) => (
                      <tr key={ev.id} className="border-b border-border/70">
                        <td className="px-2 py-2">{ev.label}</td>
                        <td className="px-2 py-2">
                          {EVENT_TYPE_LABEL[ev.event_type] || ev.event_type}
                        </td>
                        <td className="px-2 py-2">{ev.start_date}</td>
                        <td className="px-2 py-2">{ev.end_date}</td>
                        <td className="px-2 py-2 capitalize">{ev.source}</td>
                        {canWrite ? (
                          <td className="px-2 py-2">
                            <div className="flex gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => openEdit(ev)}
                                aria-label="Edit event"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => handleDelete(ev)}
                                aria-label="Delete event"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        ) : null}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      <Dialog
        open={calendarOpen}
        onClose={() => setCalendarOpen(false)}
        title={`Calendar · ${monthLabel}`}
        description="Vehicle count per day with event tags for the selected filters."
        className="max-w-3xl"
      >
        <CalendarGrid
          monthValue={monthValue}
          visibleEvents={visibleEvents}
          trafficByDate={trafficByDate}
          showTraffic
          loading={trafficLoading}
        />
      </Dialog>

      <Dialog
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? 'Edit event' : 'Add event'}
        description="Label and date range for this plaza calendar."
      >
        <form className="space-y-4" onSubmit={handleSaveEvent}>
          {formError ? (
            <p className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
              {formError}
            </p>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="ev-label">Label</Label>
            <Input
              id="ev-label"
              value={form.label}
              onChange={(e) => setForm((p) => ({ ...p, label: e.target.value }))}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ev-type">Event type</Label>
            <select
              id="ev-type"
              className="h-10 w-full rounded-sm border border-input bg-background px-2 text-body"
              value={form.event_type}
              onChange={(e) => setForm((p) => ({ ...p, event_type: e.target.value }))}
            >
              {EVENT_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ev-start">Start date</Label>
              <Input
                id="ev-start"
                type="date"
                value={form.start_date}
                onChange={(e) => setForm((p) => ({ ...p, start_date: e.target.value }))}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ev-end">End date</Label>
              <Input
                id="ev-end"
                type="date"
                value={form.end_date}
                onChange={(e) => setForm((p) => ({ ...p, end_date: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create'}
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
