import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Info, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { EntityBreadcrumb } from '@/components/entity-breadcrumb'
import { AuditExceptionsPanel, defaultAuditPeriod } from '@/components/plaza/audit-exceptions-panel'
import { PlazaNumbersDashboard } from '@/components/plaza/numbers-dashboard'
import {
  TrafficStudyPanel,
  defaultTrafficMonth,
  monthBounds,
} from '@/components/plaza/traffic-study-panel'
import {
  getCompany,
  getPlaza,
  getPlazaAuditExceptions,
  getPlazaCalendarEvents,
  getPlazaNumbers,
  getSpv,
} from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

const TABS = [
  { id: 'numbers', label: 'Numbers' },
  { id: 'traffic', label: 'Traffic study' },
  { id: 'audit', label: 'Audit exceptions' },
]

function defaultRangeForPeriod(period, availability) {
  const defaults = availability?.defaults?.[period]
  if (defaults?.start && defaults?.end) {
    return { start: String(defaults.start), end: String(defaults.end) }
  }
  return { start: '', end: '' }
}

export function PlazaDetailPage() {
  const { plazaIdentifier } = useParams()
  const [searchParams] = useSearchParams()
  const initialTab = TABS.some((t) => t.id === searchParams.get('tab'))
    ? searchParams.get('tab')
    : 'numbers'
  const [company, setCompany] = useState(null)
  const [spv, setSpv] = useState(null)
  const [plaza, setPlaza] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const [tab, setTab] = useState(initialTab)
  const [period, setPeriod] = useState('mtd')
  const [rangeDraft, setRangeDraft] = useState({ start: '', end: '' })
  const [appliedRange, setAppliedRange] = useState({ start: '', end: '' })
  const [layout, setLayout] = useState('overview')
  const [numbers, setNumbers] = useState(null)
  const [numbersLoading, setNumbersLoading] = useState(false)
  const [numbersError, setNumbersError] = useState('')
  const [auditPeriod, setAuditPeriod] = useState(defaultAuditPeriod)
  const [auditData, setAuditData] = useState(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditError, setAuditError] = useState('')
  const [trafficMonth, setTrafficMonth] = useState(defaultTrafficMonth)
  const [trafficEvents, setTrafficEvents] = useState([])
  const [trafficLoading, setTrafficLoading] = useState(false)
  const [trafficError, setTrafficError] = useState('')
  const [trafficRefreshKey, setTrafficRefreshKey] = useState(0)
  const [trafficTrend, setTrafficTrend] = useState([])
  const [hourlyAvgProfile, setHourlyAvgProfile] = useState([])
  const [weekdayAvgProfile, setWeekdayAvgProfile] = useState([])
  const [trafficTrendLoading, setTrafficTrendLoading] = useState(false)
  const suppressNumbersRefetchRef = useRef(false)

  useEffect(() => {
    suppressNumbersRefetchRef.current = false
  }, [plazaIdentifier, period])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const plazaData = await getPlaza(plazaIdentifier)
        if (!active) return
        const spvData = await getSpv(plazaData.spv_identifier)
        if (!active) return
        const companyData = await getCompany(spvData.company_identifier)
        if (!active) return
        setPlaza(plazaData)
        setSpv(spvData)
        setCompany(companyData)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load plaza')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier])

  useEffect(() => {
    if (!plazaIdentifier || tab !== 'numbers') return undefined
    if (suppressNumbersRefetchRef.current) {
      suppressNumbersRefetchRef.current = false
      return undefined
    }
    let active = true
    setNumbersLoading(true)
    setNumbersError('')
    ;(async () => {
      try {
        const hasAppliedRange = Boolean(appliedRange.start && appliedRange.end)
        const range = hasAppliedRange ? appliedRange : {}
        const data = await getPlazaNumbers(plazaIdentifier, period, range)
        if (!active) return
        setNumbers(data)
        const selection =
          data.selection || defaultRangeForPeriod(period, data.availability)
        setRangeDraft(selection)
        if (!hasAppliedRange) {
          // Hydrate appliedRange from server defaults without triggering a second fetch.
          suppressNumbersRefetchRef.current = true
          setAppliedRange(selection)
        }
      } catch (err) {
        if (active) {
          setNumbers(null)
          setNumbersError(err.message || 'Failed to load numbers')
        }
      } finally {
        if (active) setNumbersLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, period, tab, appliedRange.start, appliedRange.end])

  useEffect(() => {
    if (!plazaIdentifier || tab !== 'audit') return undefined
    let active = true
    setAuditLoading(true)
    setAuditError('')
    ;(async () => {
      try {
        const data = await getPlazaAuditExceptions(plazaIdentifier, {
          year: auditPeriod.year,
          month: auditPeriod.wholeYear ? undefined : auditPeriod.month,
        })
        if (!active) return
        setAuditData(data)
      } catch (err) {
        if (active) {
          setAuditData(null)
          setAuditError(err.message || 'Failed to load audit exceptions')
        }
      } finally {
        if (active) setAuditLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, tab, auditPeriod.year, auditPeriod.month, auditPeriod.wholeYear])

  useEffect(() => {
    if (!plazaIdentifier || tab !== 'traffic') return undefined
    let active = true
    const bounds = monthBounds(trafficMonth)
    setTrafficLoading(true)
    setTrafficError('')
    ;(async () => {
      try {
        const data = await getPlazaCalendarEvents(plazaIdentifier, {
          start: bounds.start,
          end: bounds.end,
        })
        if (!active) return
        setTrafficEvents(data.events || [])
      } catch (err) {
        if (active) {
          setTrafficEvents([])
          setTrafficError(err.message || 'Failed to load calendar events')
        }
      } finally {
        if (active) setTrafficLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, tab, trafficMonth, trafficRefreshKey])

  useEffect(() => {
    if (!plazaIdentifier || tab !== 'traffic') return undefined
    let active = true
    const bounds = monthBounds(trafficMonth)
    setTrafficTrendLoading(true)
    ;(async () => {
      try {
        const data = await getPlazaNumbers(plazaIdentifier, 'mtd', {
          start: bounds.start,
          end: bounds.end,
        })
        if (!active) return
        setTrafficTrend(data.daily_trend || [])
        setHourlyAvgProfile(data.hourly_avg_profile || [])
        setWeekdayAvgProfile(data.weekday_avg_profile || [])
      } catch {
        if (active) {
          setTrafficTrend([])
          setHourlyAvgProfile([])
          setWeekdayAvgProfile([])
        }
      } finally {
        if (active) setTrafficTrendLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaIdentifier, tab, trafficMonth])

  function handlePeriodChange(nextPeriod) {
    if (nextPeriod === period) return
    setPeriod(nextPeriod)
    const next = defaultRangeForPeriod(nextPeriod, numbers?.availability)
    setRangeDraft(next)
    setAppliedRange(next)
  }

  function handleRangeDraftChange(next) {
    setRangeDraft(next)
  }

  function handleApplyRange() {
    let start = rangeDraft.start
    let end = rangeDraft.end
    if (!start || !end) return
    if (start > end) {
      ;[start, end] = [end, start]
      setRangeDraft({ start, end })
    }
    setAppliedRange({ start, end })
  }

  const spvIdentifier = plaza?.spv_identifier || spv?.spv_identifier

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading plaza…</p>
  }

  if (error || !plaza) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Plaza unavailable</CardTitle>
          <CardDescription>{error || 'Plaza not found'}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <Link to={spvIdentifier ? `/companies/spvs/${spvIdentifier}` : '/portfolio'}>
              Back
            </Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <EntityBreadcrumb
            items={[
              { label: 'Portfolio', to: '/portfolio' },
              {
                label: company?.company_name || 'Company',
                to: `/companies/${spv.company_identifier}`,
              },
              {
                label: spv?.spv_name || 'SPV',
                to: `/companies/spvs/${spvIdentifier}`,
              },
              { label: plaza.plaza_name },
            ]}
          />
          <h1 className="text-display">{plaza.plaza_name}</h1>
          <p className="mt-1 text-body text-muted-foreground">
            {plaza.plaza_code || 'Toll plaza'}
            {plaza.district_state ? ` · ${plaza.district_state}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => setInfoOpen(true)}>
            <Info className="h-4 w-4" />
            Plaza info
          </Button>
          <Button asChild variant="outline">
            <Link to={`/companies/spvs/plazas/${plazaIdentifier}/edit`}>
              <Pencil className="h-4 w-4" />
              Edit
            </Link>
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-border pb-2">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              'rounded-sm px-3 py-1.5 text-small',
              tab === item.id
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'numbers' && (
        <div className="space-y-3">
          {numbersError && (
            <Card>
              <CardHeader>
                <CardTitle>Numbers unavailable</CardTitle>
                <CardDescription>{numbersError}</CardDescription>
              </CardHeader>
            </Card>
          )}
          {!numbers && numbersLoading && (
            <PlazaNumbersDashboard
              data={null}
              period={period}
              onPeriodChange={handlePeriodChange}
              rangeDraft={rangeDraft}
              onRangeDraftChange={handleRangeDraftChange}
              onApplyRange={handleApplyRange}
              layout={layout}
              onLayoutChange={setLayout}
              loading
            />
          )}
          {numbers && !numbersError && (
            <PlazaNumbersDashboard
              data={numbers}
              period={period}
              onPeriodChange={handlePeriodChange}
              rangeDraft={rangeDraft}
              onRangeDraftChange={handleRangeDraftChange}
              onApplyRange={handleApplyRange}
              layout={layout}
              onLayoutChange={setLayout}
              loading={numbersLoading}
            />
          )}
        </div>
      )}

      {tab === 'traffic' && (
        <TrafficStudyPanel
          plazaIdentifier={plazaIdentifier}
          events={trafficEvents}
          loading={trafficLoading}
          error={trafficError}
          monthValue={trafficMonth}
          onMonthChange={setTrafficMonth}
          dailyTrend={trafficTrend}
          hourlyAvgProfile={hourlyAvgProfile}
          weekdayAvgProfile={weekdayAvgProfile}
          trafficLoading={trafficTrendLoading}
          onRefresh={() => setTrafficRefreshKey((k) => k + 1)}
        />
      )}

      {tab === 'audit' && (
        <AuditExceptionsPanel
          data={auditData}
          loading={auditLoading}
          error={auditError}
          yearValue={auditPeriod.year}
          monthValue={auditPeriod.month}
          wholeYear={auditPeriod.wholeYear}
          onYearChange={(year) =>
            setAuditPeriod((prev) => ({ ...prev, year: String(year) }))
          }
          onMonthChange={(month) =>
            setAuditPeriod((prev) => ({ ...prev, month: String(month), wholeYear: false }))
          }
          onWholeYearChange={(enabled) =>
            setAuditPeriod((prev) => {
              if (enabled) {
                return { ...prev, wholeYear: true }
              }
              const fallback =
                prev.month ||
                String(new Date().getMonth() + 1).padStart(2, '0')
              return { ...prev, wholeYear: false, month: fallback }
            })
          }
        />
      )}

      <Dialog
        open={infoOpen}
        onClose={() => setInfoOpen(false)}
        title={plaza.plaza_name}
        description="Plaza master details"
        className="max-w-2xl"
      >
        <div className="grid max-h-[70vh] gap-4 overflow-y-auto sm:grid-cols-2">
          <ReadonlyField label="Plaza code" value={plaza.plaza_code} />
          <ReadonlyField label="Chainage" value={plaza.chainage} />
          <ReadonlyField label="District / state" value={plaza.district_state} />
          <ReadonlyField label="Latitude" value={plaza.latitude} />
          <ReadonlyField label="Longitude" value={plaza.longitude} />
          <ReadonlyField label="Tolling start date" value={plaza.tolling_start_date} />
          <ReadonlyField label="Total lanes" value={plaza.total_lanes} />
          <ReadonlyField label="LHS / RHS split" value={plaza.lhs_rhs_split} />
          <ReadonlyField label="Hybrid / ETC-only" value={plaza.hybrid_etc_only} />
          <ReadonlyField label="Shift pattern" value={plaza.shift_pattern} />
          <ReadonlyField label="Toll day cut-off" value={plaza.toll_day_cutoff} />
          <ReadonlyField label="O&M contractor" value={plaza.om_contractor} />
          <div className="sm:col-span-2">
            <ReadonlyField
              label="Source — Daily TMS report"
              value={plaza.source_daily_tms_report}
            />
          </div>
          <div className="sm:col-span-2">
            <ReadonlyField
              label="Event calendar"
              value="Managed on the Traffic study tab (upload or add events)."
            />
          </div>
          <ReadonlyField label="Updated" value={formatLocalDateTime(plaza.updated_at)} />
        </div>
      </Dialog>
    </section>
  )
}

function ReadonlyField({ label, value }) {
  return (
    <div className="space-y-1">
      <p className="text-small text-muted-foreground">{label}</p>
      <p className="text-body whitespace-pre-wrap">{value ?? '—'}</p>
    </div>
  )
}
