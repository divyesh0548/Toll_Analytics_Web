import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { PeriodRangeControls } from '@/components/plaza/numbers-dashboard'
import {
  OverallTollDashboard,
  canShowYoy,
} from '@/components/plaza/overall-toll-dashboard'
import {
  getPlaza,
  getPlazaNumbers,
  getSpv,
  listCompanies,
  listPlazas,
  listSpvs,
} from '@/lib/api'
import { useTheme } from '@/components/theme-provider'

function defaultRangeForPeriod(period, availability) {
  const defaults = availability?.defaults?.[period]
  if (defaults?.start && defaults?.end) {
    return { start: String(defaults.start), end: String(defaults.end) }
  }
  return { start: '', end: '' }
}

export function OverallTollAnalysisPage() {
  const { theme } = useTheme()
  const dark = theme === 'dark'
  const [searchParams, setSearchParams] = useSearchParams()

  const [companies, setCompanies] = useState([])
  const [spvs, setSpvs] = useState([])
  const [plazas, setPlazas] = useState([])
  const [filtersLoading, setFiltersLoading] = useState(true)
  const [filtersError, setFiltersError] = useState('')

  const [companyId, setCompanyId] = useState(searchParams.get('company') || '')
  const [spvId, setSpvId] = useState(searchParams.get('spv') || '')
  const [plazaId, setPlazaId] = useState(searchParams.get('plaza') || '')

  const [period, setPeriod] = useState('mtd')
  const [rangeDraft, setRangeDraft] = useState({ start: '', end: '' })
  const [appliedRange, setAppliedRange] = useState({ start: '', end: '' })
  const [numbers, setNumbers] = useState(null)
  const [numbersLoading, setNumbersLoading] = useState(false)
  const [numbersError, setNumbersError] = useState('')
  const suppressRefetchRef = useRef(false)
  const bootstrappedPlazaRef = useRef('')

  const companyOptions = useMemo(
    () =>
      companies.map((c) => ({
        value: c.company_identifier,
        label: c.company_name,
        meta: c.company_identifier,
      })),
    [companies],
  )
  const spvOptions = useMemo(
    () =>
      spvs.map((s) => ({
        value: s.spv_identifier,
        label: s.spv_name,
        meta: s.spv_identifier,
      })),
    [spvs],
  )
  const plazaOptions = useMemo(
    () =>
      plazas.map((p) => ({
        value: p.plaza_identifier,
        label: p.plaza_name,
        meta: p.plaza_code || p.plaza_identifier,
      })),
    [plazas],
  )

  const selectedPlaza = plazas.find((p) => p.plaza_identifier === plazaId) || null
  const showYoy = canShowYoy(period, appliedRange, numbers?.availability)

  // Sync filters → URL
  useEffect(() => {
    const next = new URLSearchParams()
    if (companyId) next.set('company', companyId)
    if (spvId) next.set('spv', spvId)
    if (plazaId) next.set('plaza', plazaId)
    setSearchParams(next, { replace: true })
  }, [companyId, spvId, plazaId, setSearchParams])

  // Load companies; optionally resolve plaza → spv → company from query
  useEffect(() => {
    let active = true
    ;(async () => {
      setFiltersLoading(true)
      setFiltersError('')
      try {
        const companyData = await listCompanies()
        if (!active) return
        setCompanies(companyData.companies || [])

        const plazaParam = searchParams.get('plaza') || ''
        if (plazaParam && bootstrappedPlazaRef.current !== plazaParam) {
          bootstrappedPlazaRef.current = plazaParam
          const plazaData = await getPlaza(plazaParam)
          if (!active) return
          const spvData = await getSpv(plazaData.spv_identifier)
          if (!active) return
          setCompanyId(spvData.company_identifier)
          setSpvId(spvData.spv_identifier)
          setPlazaId(plazaData.plaza_identifier)
        }
      } catch (err) {
        if (active) setFiltersError(err.message || 'Failed to load filters')
      } finally {
        if (active) setFiltersLoading(false)
      }
    })()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bootstrap once from initial query
  }, [])

  // Load SPVs when company changes
  useEffect(() => {
    if (!companyId) {
      setSpvs([])
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const data = await listSpvs(companyId)
        if (!active) return
        setSpvs(data.spvs || [])
      } catch (err) {
        if (active) {
          setSpvs([])
          setFiltersError(err.message || 'Failed to load SPVs')
        }
      }
    })()
    return () => {
      active = false
    }
  }, [companyId])

  // Load plazas when SPV changes
  useEffect(() => {
    if (!spvId) {
      setPlazas([])
      return undefined
    }
    let active = true
    ;(async () => {
      try {
        const data = await listPlazas(spvId)
        if (!active) return
        setPlazas(data.plazas || [])
      } catch (err) {
        if (active) {
          setPlazas([])
          setFiltersError(err.message || 'Failed to load plazas')
        }
      }
    })()
    return () => {
      active = false
    }
  }, [spvId])

  useEffect(() => {
    suppressRefetchRef.current = false
  }, [plazaId, period])

  // Fetch numbers when plaza + applied range ready
  useEffect(() => {
    if (!plazaId) {
      setNumbers(null)
      setNumbersError('')
      return undefined
    }
    if (suppressRefetchRef.current) {
      suppressRefetchRef.current = false
      return undefined
    }
    let active = true
    setNumbersLoading(true)
    setNumbersError('')
    ;(async () => {
      try {
        const hasApplied = Boolean(appliedRange.start && appliedRange.end)
        const data = await getPlazaNumbers(
          plazaId,
          period,
          hasApplied ? appliedRange : {},
        )
        if (!active) return
        setNumbers(data)
        if (!hasApplied) {
          const next = defaultRangeForPeriod(period, data.availability)
          setRangeDraft(next)
          setAppliedRange(next)
          suppressRefetchRef.current = true
        } else if (data.selection?.start && data.selection?.end) {
          const echoed = {
            start: String(data.selection.start),
            end: String(data.selection.end),
          }
          setRangeDraft(echoed)
        }
      } catch (err) {
        if (active) {
          setNumbers(null)
          setNumbersError(err.message || 'Failed to load analytics')
        }
      } finally {
        if (active) setNumbersLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [plazaId, period, appliedRange.start, appliedRange.end])

  function handleCompanyChange(value) {
    setCompanyId(value || '')
    setSpvId('')
    setPlazaId('')
    setNumbers(null)
    setAppliedRange({ start: '', end: '' })
    setRangeDraft({ start: '', end: '' })
  }

  function handleSpvChange(value) {
    setSpvId(value || '')
    setPlazaId('')
    setNumbers(null)
    setAppliedRange({ start: '', end: '' })
    setRangeDraft({ start: '', end: '' })
  }

  function handlePlazaChange(value) {
    setPlazaId(value || '')
    setNumbers(null)
    setAppliedRange({ start: '', end: '' })
    setRangeDraft({ start: '', end: '' })
  }

  function handlePeriodChange(nextPeriod) {
    if (nextPeriod === period) return
    setPeriod(nextPeriod)
    const next = defaultRangeForPeriod(nextPeriod, numbers?.availability)
    setRangeDraft(next)
    setAppliedRange(next)
    suppressRefetchRef.current = false
  }

  function handleApplyRange() {
    setAppliedRange({ ...rangeDraft })
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-small text-muted-foreground">
          <Link to="/portfolio" className="hover:text-foreground">
            Portfolio
          </Link>
          {' / '}
          Overall toll analysis
        </p>
        <h1 className="text-display">Overall toll analysis</h1>
        <p className="mt-1 text-body text-muted-foreground">
          Plaza-level transactions, revenue, and category mix
          {selectedPlaza ? ` · ${selectedPlaza.plaza_name}` : ''}
        </p>
      </div>

      <div className="grid gap-3 rounded-sm border border-border bg-card p-3 sm:grid-cols-3">
        <label className="space-y-1">
          <span className="block text-small text-muted-foreground">Company</span>
          <SearchableSelect
            options={companyOptions}
            value={companyId}
            onChange={handleCompanyChange}
            placeholder={filtersLoading ? 'Loading…' : 'Select company'}
            disabled={filtersLoading}
          />
        </label>
        <label className="space-y-1">
          <span className="block text-small text-muted-foreground">SPV</span>
          <SearchableSelect
            options={spvOptions}
            value={spvId}
            onChange={handleSpvChange}
            placeholder={!companyId ? 'Select company first' : 'Select SPV'}
            disabled={!companyId || filtersLoading}
          />
        </label>
        <label className="space-y-1">
          <span className="block text-small text-muted-foreground">Fee plaza</span>
          <SearchableSelect
            options={plazaOptions}
            value={plazaId}
            onChange={handlePlazaChange}
            placeholder={!spvId ? 'Select SPV first' : 'Select plaza'}
            disabled={!spvId || filtersLoading}
          />
        </label>
      </div>

      {filtersError ? (
        <Card>
          <CardHeader>
            <CardTitle>Filters unavailable</CardTitle>
            <CardDescription>{filtersError}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {plazaId ? (
        <PeriodRangeControls
          period={period}
          onPeriodChange={handlePeriodChange}
          draft={rangeDraft}
          onDraftChange={setRangeDraft}
          onApply={handleApplyRange}
          availability={numbers?.availability}
          disabled={numbersLoading && !numbers}
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Select a plaza</CardTitle>
            <CardDescription>
              Choose company, SPV and plaza to view analytics.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {numbersError ? (
        <Card>
          <CardHeader>
            <CardTitle>Analytics unavailable</CardTitle>
            <CardDescription>{numbersError}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {plazaId && numbersLoading && !numbers ? (
        <div className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span>Loading dataset…</span>
        </div>
      ) : null}

      {plazaId && numbers ? (
        <div className="relative">
          {numbersLoading ? (
            <div className="absolute inset-0 z-20 flex items-center justify-center rounded-sm bg-background/70">
              <Loader2 className="h-7 w-7 animate-spin text-primary" />
            </div>
          ) : null}
          <OverallTollDashboard data={numbers} showYoy={showYoy} dark={dark} />
        </div>
      ) : null}
    </div>
  )
}
