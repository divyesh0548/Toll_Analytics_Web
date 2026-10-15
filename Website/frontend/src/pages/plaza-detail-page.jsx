import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Info, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { PageHeader } from '@/components/ui/page-header'
import { DashboardSkeleton } from '@/components/ui/skeleton'
import {
  UnderlineTabs,
  underlineTabClass,
} from '@/components/ui/segmented-control'
import { EntityBreadcrumb } from '@/components/entity-breadcrumb'
import { AuditExceptionsPanel, defaultAuditPeriod } from '@/components/plaza/audit-exceptions-panel'
import { PlazaNumbersDashboard } from '@/components/plaza/numbers-dashboard'
import {
  TrafficStudyPanel,
  defaultTrafficMonth,
  monthBounds,
  resolveTrafficMonth,
} from '@/components/plaza/traffic-study-panel'
import { useAuth } from '@/components/auth-provider'
import {
  getCompany,
  getPlaza,
  getPlazaAuditExceptions,
  getPlazaCalendarEvents,
  getPlazaNumbers,
  getSpv,
} from '@/lib/api'
import { formatLocalDateTime } from '@/lib/utils'

const TABS = [
  { id: 'overall', label: 'Overall', to: '/overall-toll-analysis' },
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
  const { developmentExceptions } = useAuth()
  const initialTab = TABS.some((t) => t.id === searchParams.get('tab') && t.id !== 'overall')
    ? searchParams.get('tab')
    : 'numbers'
  const [company, setCompany] = useState(null)
  const [spv, setSpv] = useState(null)
  const [plaza, setPlaza] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const [tab, setTab] = useState(initialTab)
  const [periodDraft, setPeriodDraft] = useState('mtd')
  const [periodApplied, setPeriodApplied] = useState('mtd')
  const [rangeDraft, setRangeDraft] = useState({ start: '', end: '' })
  const [appliedRange, setAppliedRange] = useState({ start: '', end: '' })
  const [layout, setLayout] = useState('overview')
  const [numbers, setNumbers] = useState(null)
  const [numbersLoading, setNumbersLoading] = useState(false)
  const [numbersError, setNumbersError] = useState('')
  const [auditDraft, setAuditDraft] = useState(() => ({
    ...defaultAuditPeriod(),
    metricsSource: 'manual',
  }))
  const [auditApplied, setAuditApplied] = useState(() => ({
    ...defaultAuditPeriod(),
    metricsSource: 'manual',
  }))
  const [auditData, setAuditData] = useState(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [auditError, setAuditError] = useState('')
  const [auditRefreshKey, setAuditRefreshKey] = useState(0)
  const [trafficMonth, setTrafficMonth] = useState(defaultTrafficMonth)
  const [trafficEvents, setTrafficEvents] = useState([])
  const [trafficLoading, setTrafficLoading] = useState(false)
  const [trafficError, setTrafficError] = useState('')
  const [trafficRefreshKey, setTrafficRefreshKey] = useState(0)
  const [trafficTrend, setTrafficTrend] = useState([])
  const [hourlyAvgProfile, setHourlyAvgProfile] = useState([])
  const [weekdayAvgProfile, setWeekdayAvgProfile] = useState([])
  const [trafficTrendLoading, setTrafficTrendLoading] = useState(false)
  const [trafficAvailability, setTrafficAvailability] = useState(null)
  const suppressNumbersRefetchRef = useRef(false)

  useEffect(() => {
    suppressNumbersRefetchRef.current = false
  }, [plazaIdentifier, periodApplied])

  useEffect(() => {
    setTrafficMonth(defaultTrafficMonth())
    setTrafficAvailability(null)
    setPeriodDraft('mtd')
    setPeriodApplied('mtd')
    setRangeDraft({ start: '', end: '' })
    setAppliedRange({ start: '', end: '' })
  }, [plazaIdentifier])

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
        const data = await getPlazaNumbers(plazaIdentifier, periodApplied, range)
        if (!active) return
        setNumbers(data)
        const selection =
          data.selection ||
          defaultRangeForPeriod(periodApplied, data.availability)
        setRangeDraft(selection)
        setPeriodDraft(periodApplied)
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
  }, [
    plazaIdentifier,
    periodApplied,
    tab,
    appliedRange.start,
    appliedRange.end,
  ])

  useEffect(() => {
    const defaults = {
      ...defaultAuditPeriod(),
      metricsSource: 'manual',
    }
    setAuditDraft(defaults)
    setAuditApplied(defaults)
    setAuditData(null)
    setAuditError('')
  }, [plazaIdentifier])

  // Without Development_Exceptions, always use manual (separate-job) metrics tables.
  useEffect(() => {
    if (developmentExceptions) return
    setAuditDraft((prev) =>
      prev.metricsSource === 'manual' ? prev : { ...prev, metricsSource: 'manual' },
    )
    setAuditApplied((prev) =>
      prev.metricsSource === 'manual' ? prev : { ...prev, metricsSource: 'manual' },
    )
  }, [developmentExceptions])

  useEffect(() => {
    if (!plazaIdentifier || tab !== 'audit') return undefined
    let active = true
    setAuditLoading(true)
    setAuditError('')
    const metricsSource = developmentExceptions
      ? auditApplied.metricsSource || 'manual'
      : 'manual'
    ;(async () => {
      try {
        const data = await getPlazaAuditExceptions(plazaIdentifier, {
          year: auditApplied.year,
          month: auditApplied.wholeYear ? undefined : auditApplied.month,
          metricsSource,
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
  }, [
    plazaIdentifier,
    tab,
    auditApplied.year,
    auditApplied.month,
    auditApplied.wholeYear,
    auditApplied.metricsSource,
    auditRefreshKey,
    developmentExceptions,
  ])

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
        if (data.availability) setTrafficAvailability(data.availability)
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

  useEffect(() => {
    if (!trafficAvailability?.months?.length) return
    setTrafficMonth((prev) => resolveTrafficMonth(trafficAvailability, prev))
  }, [trafficAvailability])

  function handlePeriodChange(nextPeriod) {
    if (nextPeriod === periodDraft) return
    setPeriodDraft(nextPeriod)
    setRangeDraft(defaultRangeForPeriod(nextPeriod, numbers?.availability))
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
    if (periodDraft === 'day') {
      const startDate = new Date(`${start}T00:00:00`)
      const endDate = new Date(`${end}T00:00:00`)
      const span =
        Math.floor((endDate.getTime() - startDate.getTime()) / 86400000) + 1
      if (span < 5) return
    }
    setPeriodApplied(periodDraft)
    setAppliedRange({ start, end })
  }

  const spvIdentifier = plaza?.spv_identifier || spv?.spv_identifier

  if (loading) {
    return (
      <section className="space-y-6">
        <div className="border-b border-border/80 pb-5 space-y-2">
          <div className="h-3 w-48 animate-pulse rounded-sm bg-muted" />
          <div className="h-8 w-64 animate-pulse rounded-sm bg-muted" />
          <div className="h-4 w-40 animate-pulse rounded-sm bg-muted" />
        </div>
        <DashboardSkeleton kpis={5} />
      </section>
    )
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
      <PageHeader
        eyebrow={
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
        }
        title={plaza.plaza_name}
        description={
          <>
            {plaza.plaza_code || 'Toll plaza'}
            {plaza.district_state ? ` · ${plaza.district_state}` : ''}
          </>
        }
        actions={
          <>
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
          </>
        }
      />

      <UnderlineTabs>
        {TABS.map((item) =>
          item.to ? (
            <Link
              key={item.id}
              to={`${item.to}?plaza=${encodeURIComponent(plazaIdentifier)}&from=plaza`}
              className={underlineTabClass(false)}
            >
              {item.label}
            </Link>
          ) : (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={underlineTabClass(tab === item.id)}
            >
              {item.label}
            </button>
          ),
        )}
      </UnderlineTabs>

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
              period={periodDraft}
              appliedPeriod={periodApplied}
              onPeriodChange={handlePeriodChange}
              rangeDraft={rangeDraft}
              appliedRange={appliedRange}
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
              period={periodDraft}
              appliedPeriod={periodApplied}
              onPeriodChange={handlePeriodChange}
              rangeDraft={rangeDraft}
              appliedRange={appliedRange}
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
          availableMonths={trafficAvailability?.months || []}
          availableYears={trafficAvailability?.years || []}
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
          yearValue={auditDraft.year}
          monthValue={auditDraft.month}
          wholeYear={auditDraft.wholeYear}
          metricsSource={
            developmentExceptions ? auditDraft.metricsSource || 'manual' : 'manual'
          }
          showMetricsSource={Boolean(developmentExceptions)}
          canApply={
            auditDraft.year !== auditApplied.year ||
            auditDraft.month !== auditApplied.month ||
            Boolean(auditDraft.wholeYear) !== Boolean(auditApplied.wholeYear) ||
            (Boolean(developmentExceptions) &&
              (auditDraft.metricsSource || 'manual') !==
                (auditApplied.metricsSource || 'manual'))
          }
          onYearChange={(year) =>
            setAuditDraft((prev) => ({ ...prev, year: String(year) }))
          }
          onMonthChange={(month) =>
            setAuditDraft((prev) => ({
              ...prev,
              month: String(month),
              wholeYear: false,
            }))
          }
          onWholeYearChange={(enabled) =>
            setAuditDraft((prev) => {
              if (enabled) {
                return { ...prev, wholeYear: true }
              }
              const fallback =
                prev.month ||
                String(new Date().getMonth() + 1).padStart(2, '0')
              return { ...prev, wholeYear: false, month: fallback }
            })
          }
          onMetricsSourceChange={(source) =>
            setAuditDraft((prev) => ({
              ...prev,
              metricsSource: source || 'manual',
            }))
          }
          onRefresh={() => {
            setAuditApplied({
              year: String(auditDraft.year),
              month: String(auditDraft.month),
              wholeYear: Boolean(auditDraft.wholeYear),
              metricsSource: auditDraft.metricsSource || 'manual',
            })
            setAuditRefreshKey((key) => key + 1)
          }}
          onApply={() =>
            setAuditApplied({
              year: String(auditDraft.year),
              month: String(auditDraft.month),
              wholeYear: Boolean(auditDraft.wholeYear),
              metricsSource: auditDraft.metricsSource || 'manual',
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
