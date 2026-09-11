import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Info, Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { PlazaNumbersDashboard } from '@/components/plaza/numbers-dashboard'
import { getCompany, getPlaza, getPlazaNumbers, getSpv } from '@/lib/api'
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
  const [company, setCompany] = useState(null)
  const [spv, setSpv] = useState(null)
  const [plaza, setPlaza] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const [tab, setTab] = useState('numbers')
  const [period, setPeriod] = useState('mtd')
  const [rangeDraft, setRangeDraft] = useState({ start: '', end: '' })
  const [appliedRange, setAppliedRange] = useState({ start: '', end: '' })
  const [layout, setLayout] = useState('overview')
  const [numbers, setNumbers] = useState(null)
  const [numbersLoading, setNumbersLoading] = useState(false)
  const [numbersError, setNumbersError] = useState('')

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
    let active = true
    setNumbersLoading(true)
    setNumbersError('')
    ;(async () => {
      try {
        const range =
          appliedRange.start && appliedRange.end ? appliedRange : {}
        const data = await getPlazaNumbers(plazaIdentifier, period, range)
        if (!active) return
        setNumbers(data)
        const selection =
          data.selection || defaultRangeForPeriod(period, data.availability)
        setRangeDraft(selection)
        if (!appliedRange.start || !appliedRange.end) {
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
        <div className="space-y-1">
          <p className="text-small text-muted-foreground">
            <Link to="/portfolio" className="hover:text-primary">
              Portfolio
            </Link>{' '}
            ›{' '}
            <Link
              to={`/companies/${spv.company_identifier}`}
              className="hover:text-primary"
            >
              {company?.company_name || 'Company'}
            </Link>{' '}
            ›{' '}
            <Link to={`/companies/spvs/${spvIdentifier}`} className="hover:text-primary">
              {spv?.spv_name || 'SPV'}
            </Link>{' '}
            › Plaza
          </p>
          <h1 className="text-display">{plaza.plaza_name}</h1>
          <p className="text-body text-muted-foreground">
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
            <Link to={`/companies/spvs/${spvIdentifier}/plazas/${plazaIdentifier}/edit`}>
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
        <Card>
          <CardHeader>
            <CardTitle>Traffic study</CardTitle>
            <CardDescription>Coming soon — gap and flow analysis will appear here.</CardDescription>
          </CardHeader>
        </Card>
      )}

      {tab === 'audit' && (
        <Card>
          <CardHeader>
            <CardTitle>Audit exceptions</CardTitle>
            <CardDescription>Coming soon — exception flags will appear here.</CardDescription>
          </CardHeader>
        </Card>
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
            <ReadonlyField label="Event calendar" value={plaza.event_calendar} />
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
