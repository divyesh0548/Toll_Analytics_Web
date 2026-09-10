import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Building2, Plus } from 'lucide-react'
import Chart from 'react-apexcharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { listCompanies } from '@/lib/api'
import { formatLocalDateTime } from '@/lib/utils'
import { useTheme } from '@/components/theme-provider'

function PortfolioSpark({ dark }) {
  const options = {
    chart: {
      type: 'area',
      sparkline: { enabled: true },
      animations: { enabled: true, speed: 500 },
    },
    stroke: { curve: 'smooth', width: 2 },
    fill: {
      type: 'gradient',
      gradient: { opacityFrom: 0.35, opacityTo: 0.05 },
    },
    colors: [dark ? '#6fbf7a' : '#2f7a45'],
    tooltip: { enabled: false },
  }
  const series = [{ data: [12, 18, 14, 22, 19, 28, 24] }]
  return <Chart options={options} series={series} type="area" height={56} />
}

export function PortfolioPage() {
  const { theme } = useTheme()
  const [companies, setCompanies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const data = await listCompanies()
        if (active) setCompanies(data.companies || [])
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
            Open a company to view SPVs and details.
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
        {companies.map((company) => (
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
                    <p className="text-subheader">—</p>
                  </div>
                  <div>
                    <p className="text-small text-muted-foreground">Contacts</p>
                    <p className="text-subheader">{company.contacts?.length ?? 0}</p>
                  </div>
                </div>
                <PortfolioSpark dark={theme === 'dark'} />
                <p className="text-small text-muted-foreground">
                  Updated {formatLocalDateTime(company.updated_at)}
                </p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </section>
  )
}
