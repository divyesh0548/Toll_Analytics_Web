import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, ChevronDown, ChevronRight, Plus } from 'lucide-react'
import Chart from 'react-apexcharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getPortfolioRollup, getPortfolioVolume, listCompanies } from '@/lib/api'
import { categoryTooltipXFormatter, categoryXAxis } from '@/lib/chart-axis'
import { cn, formatLocalDateTime } from '@/lib/utils'
import { useTheme } from '@/components/theme-provider'

function formatCount(value) {
  if (value == null) return '—'
  return Number(value).toLocaleString('en-IN')
}

function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString('en-IN', {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  })
}

function CompanyVolumeChart({ series, dark }) {
  const fullCategories = series.map((p) => p.label)
  const text = dark ? '#e5e7eb' : '#334155'
  const xAxis = categoryXAxis(fullCategories, { colors: text, fontSize: '10px' }, 4)
  const data = series.map((p) => p.traffic)
  const options = {
    chart: {
      type: 'area',
      sparkline: { enabled: false },
      toolbar: { show: false },
      animations: { enabled: true, speed: 500 },
      fontFamily: 'Archivo, sans-serif',
      foreColor: text,
      background: 'transparent',
    },
    theme: { mode: dark ? 'dark' : 'light' },
    stroke: { curve: 'smooth', width: 2 },
    fill: {
      type: 'gradient',
      gradient: { opacityFrom: 0.35, opacityTo: 0.05 },
    },
    colors: [dark ? '#6fbf7a' : '#2f7a45'],
    dataLabels: { enabled: false },
    xaxis: {
      categories: xAxis.categories,
      labels: {
        ...xAxis.labels,
        hideOverlappingLabels: true,
        trim: true,
      },
      axisBorder: { show: false },
      axisTicks: { show: false },
    },
    yaxis: { show: false },
    grid: { show: false },
    tooltip: {
      theme: dark ? 'dark' : 'light',
      x: { formatter: categoryTooltipXFormatter(fullCategories) },
      y: { formatter: (v) => Number(v).toLocaleString('en-IN') },
    },
  }
  return (
    <Chart
      options={options}
      series={[{ name: 'Vehicles', data }]}
      type="area"
      height={88}
    />
  )
}

function PortfolioRollupTable({ rollup }) {
  const [openCompanies, setOpenCompanies] = useState(() => new Set())
  const [openSpvs, setOpenSpvs] = useState(() => new Set())

  const companies = rollup?.companies || []
  const yearLabel = rollup?.label || (rollup?.year ? `All figures are for Year ${rollup.year}` : '')

  function toggleCompany(id) {
    setOpenCompanies((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSpv(id) {
    setOpenSpvs((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>All entities</CardTitle>
        <CardDescription>
          Expandable company → SPV → plaza roll-up
          {yearLabel ? ` · ${yearLabel}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        {yearLabel ? (
          <p className="mb-3 text-small font-medium text-muted-foreground">{yearLabel}</p>
        ) : null}
        <table className="w-full min-w-[40rem] border-collapse text-left text-body">
          <thead>
            <tr className="border-b border-border text-small text-muted-foreground">
              <th className="px-2 py-2 font-medium">Entity</th>
              <th className="px-2 py-2 font-medium">Type</th>
              <th className="px-2 py-2 font-medium text-right">Traffic</th>
              <th className="px-2 py-2 font-medium text-right">Revenue</th>
            </tr>
          </thead>
          <tbody>
            {companies.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-2 py-6 text-center text-muted-foreground">
                  No companies in roll-up.
                </td>
              </tr>
            ) : (
              companies.map((company) => {
                const companyOpen = openCompanies.has(company.company_identifier)
                return (
                  <FragmentRows
                    key={company.company_identifier}
                    company={company}
                    companyOpen={companyOpen}
                    openSpvs={openSpvs}
                    onToggleCompany={() => toggleCompany(company.company_identifier)}
                    onToggleSpv={toggleSpv}
                  />
                )
              })
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function FragmentRows({ company, companyOpen, openSpvs, onToggleCompany, onToggleSpv }) {
  return (
    <>
      <tr className="border-b border-border/70 bg-muted/20">
        <td className="px-2 py-2">
          <button
            type="button"
            onClick={onToggleCompany}
            className="inline-flex items-center gap-1 font-medium hover:underline"
          >
            {companyOpen ? (
              <ChevronDown className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0" />
            )}
            <Link
              to={`/companies/${company.company_identifier}`}
              className="hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {company.company_name}
            </Link>
          </button>
        </td>
        <td className="px-2 py-2 text-muted-foreground">Company</td>
        <td className="px-2 py-2 text-right font-medium">{formatCount(company.traffic)}</td>
        <td className="px-2 py-2 text-right font-medium">{formatMoney(company.revenue)}</td>
      </tr>
      {companyOpen
        ? (company.spvs || []).map((spv) => {
            const spvOpen = openSpvs.has(spv.spv_identifier)
            return (
              <SpvRows
                key={spv.spv_identifier}
                spv={spv}
                spvOpen={spvOpen}
                onToggleSpv={() => onToggleSpv(spv.spv_identifier)}
              />
            )
          })
        : null}
    </>
  )
}

function SpvRows({ spv, spvOpen, onToggleSpv }) {
  return (
    <>
      <tr className="border-b border-border/50">
        <td className="px-2 py-2 pl-8">
          <button
            type="button"
            onClick={onToggleSpv}
            className="inline-flex items-center gap-1 hover:underline"
          >
            {spvOpen ? (
              <ChevronDown className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0" />
            )}
            <Link
              to={`/companies/spvs/${spv.spv_identifier}`}
              className="hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {spv.spv_name}
            </Link>
          </button>
        </td>
        <td className="px-2 py-2 text-muted-foreground">SPV</td>
        <td className="px-2 py-2 text-right">{formatCount(spv.traffic)}</td>
        <td className="px-2 py-2 text-right">{formatMoney(spv.revenue)}</td>
      </tr>
      {spvOpen
        ? (spv.plazas || []).map((plaza) => (
            <tr key={plaza.plaza_identifier} className="border-b border-border/40">
              <td className="px-2 py-2 pl-14">
                <Link
                  to={`/companies/spvs/plazas/${plaza.plaza_identifier}`}
                  className="hover:underline"
                >
                  {plaza.plaza_name}
                </Link>
              </td>
              <td className="px-2 py-2 text-muted-foreground">Plaza</td>
              <td className="px-2 py-2 text-right">{formatCount(plaza.traffic)}</td>
              <td className="px-2 py-2 text-right">{formatMoney(plaza.revenue)}</td>
            </tr>
          ))
        : null}
    </>
  )
}

export function PortfolioPage() {
  const { theme } = useTheme()
  const [companies, setCompanies] = useState([])
  const [volumeByCompany, setVolumeByCompany] = useState({})
  const [rollup, setRollup] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [companyData, volumeData, rollupData] = await Promise.all([
          listCompanies(),
          getPortfolioVolume().catch(() => ({ companies: [] })),
          getPortfolioRollup().catch(() => null),
        ])
        if (!active) return
        setCompanies(companyData.companies || [])
        const map = {}
        for (const row of volumeData.companies || []) {
          map[row.company_identifier] = row
        }
        setVolumeByCompany(map)
        setRollup(rollupData)
      } catch (err) {
        if (active) setError(err.message || 'Failed to load companies')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const dark = theme === 'dark'

  const topCompanies = useMemo(() => {
    const ranked = [...companies].map((company) => {
      const volume = volumeByCompany[company.company_identifier]
      const series = volume?.series || []
      const total = series.reduce((sum, row) => sum + (row.traffic || 0), 0)
      return { company, volume, series, total }
    })
    ranked.sort((a, b) => b.total - a.total)
    return ranked.slice(0, 3)
  }, [companies, volumeByCompany])

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading portfolio…</p>
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Could not load portfolio</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/companies/new">Create company</Link>
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (companies.length === 0) {
    return (
      <section className="mx-auto flex max-w-xl flex-col items-center gap-5 py-16 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-sm bg-accent text-primary">
          <Building2 className="h-7 w-7" />
        </div>
        <div className="space-y-2">
          <h1 className="text-display">No companies yet</h1>
          <p className="text-body text-muted-foreground">
            Portfolio details stay hidden until at least one company exists. Create your first
            company to start the hierarchy.
          </p>
        </div>
        <Button asChild size="lg">
          <Link to="/companies/new">
            <Plus className="h-4 w-4" />
            Create company
          </Link>
        </Button>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="text-small uppercase tracking-[0.14em] text-muted-foreground">
            Portfolio
          </p>
          <h1 className="text-display">Companies</h1>
          <p className="text-body text-muted-foreground">
            Top companies by volume, with full expandable hierarchy below.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline">
            <Link to="/companies/spvs/new">
              <Plus className="h-4 w-4" />
              New SPV
            </Link>
          </Button>
          <Button asChild>
            <Link to="/companies/new">
              <Plus className="h-4 w-4" />
              New company
            </Link>
          </Button>
        </div>
      </div>

      <div>
        <p className="mb-3 text-small text-muted-foreground">
          Top {topCompanies.length} by volume
        </p>
        <div className={cn('grid gap-4', 'sm:grid-cols-2 xl:grid-cols-3')}>
          {topCompanies.map(({ company, volume, series, total }) => (
            <Link
              key={company.company_identifier}
              to={`/companies/${company.company_identifier}`}
              className="block transition hover:-translate-y-0.5"
            >
              <Card className="h-full overflow-hidden">
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle>{company.company_name}</CardTitle>
                      <CardDescription>{company.short_code}</CardDescription>
                    </div>
                    <span className="rounded-sm bg-secondary px-2 py-1 text-small text-secondary-foreground">
                      Company
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <p className="text-small text-muted-foreground">SPVs</p>
                      <p className="text-subheader">{company.spv_count ?? 0}</p>
                    </div>
                    <div>
                      <p className="text-small text-muted-foreground">Plazas</p>
                      <p className="text-subheader">
                        {company.plaza_count ?? volume?.plaza_count ?? 0}
                      </p>
                    </div>
                    <div>
                      <p className="text-small text-muted-foreground">Volume</p>
                      <p className="text-subheader">{total.toLocaleString('en-IN')}</p>
                    </div>
                  </div>
                  {series.length > 0 ? (
                    <CompanyVolumeChart series={series} dark={dark} />
                  ) : (
                    <p className="py-6 text-center text-small text-muted-foreground">
                      No traffic data yet
                    </p>
                  )}
                  <p className="text-small text-muted-foreground">
                    Updated {formatLocalDateTime(company.updated_at)}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </div>

      {rollup ? <PortfolioRollupTable rollup={rollup} /> : null}
    </section>
  )
}
