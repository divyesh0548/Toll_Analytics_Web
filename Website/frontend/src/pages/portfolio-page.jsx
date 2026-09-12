import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, Plus } from 'lucide-react'
import Chart from 'react-apexcharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getPortfolioVolume, listCompanies } from '@/lib/api'
import { categoryTooltipXFormatter, categoryXAxis } from '@/lib/chart-axis'
import { formatLocalDateTime } from '@/lib/utils'
import { useTheme } from '@/components/theme-provider'

function CompanyVolumeChart({ series, dark }) {
  const fullCategories = series.map((p) => p.label)
  const text = dark ? '#e5e7eb' : '#334155'
  const xAxis = categoryXAxis(fullCategories, { colors: text, fontSize: '10px' })
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
      labels: xAxis.labels,
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

export function PortfolioPage() {
  const { theme } = useTheme()
  const [companies, setCompanies] = useState([])
  const [volumeByCompany, setVolumeByCompany] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [companyData, volumeData] = await Promise.all([
          listCompanies(),
          getPortfolioVolume().catch(() => ({ companies: [] })),
        ])
        if (!active) return
        setCompanies(companyData.companies || [])
        const map = {}
        for (const row of volumeData.companies || []) {
          map[row.company_identifier] = row
        }
        setVolumeByCompany(map)
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
            Vehicle volume by company.
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

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {companies.map((company) => {
          const volume = volumeByCompany[company.company_identifier]
          const series = volume?.series || []
          const total = series.reduce((sum, row) => sum + (row.traffic || 0), 0)
          return (
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
          )
        })}
      </div>
    </section>
  )
}
