import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Pencil } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getCompany, getPlaza, getSpv } from '@/lib/api'
import { formatLocalDateTime } from '@/lib/utils'

export function PlazaDetailPage() {
  const { spvIdentifier, plazaIdentifier } = useParams()
  const [company, setCompany] = useState(null)
  const [spv, setSpv] = useState(null)
  const [plaza, setPlaza] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [plazaData, spvData] = await Promise.all([
          getPlaza(plazaIdentifier),
          getSpv(spvIdentifier),
        ])
        if (!active) return
        if (plazaData.spv_identifier !== spvIdentifier) {
          throw new Error('Plaza does not belong to this SPV')
        }
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
  }, [spvIdentifier, plazaIdentifier])

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
            <Link to={`/companies/spvs/${spvIdentifier}`}>Back to SPV</Link>
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
        <Button asChild variant="outline">
          <Link to={`/companies/spvs/${spvIdentifier}/plazas/${plazaIdentifier}/edit`}>
            <Pencil className="h-4 w-4" />
            Edit plaza
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Identity & location</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField label="Plaza code" value={plaza.plaza_code} />
          <ReadonlyField label="Chainage" value={plaza.chainage} />
          <ReadonlyField label="District / state" value={plaza.district_state} />
          <ReadonlyField label="Latitude" value={plaza.latitude} />
          <ReadonlyField label="Longitude" value={plaza.longitude} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operations</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField label="Tolling start date" value={plaza.tolling_start_date} />
          <ReadonlyField label="Total lanes" value={plaza.total_lanes} />
          <ReadonlyField label="LHS / RHS split" value={plaza.lhs_rhs_split} />
          <ReadonlyField label="Hybrid / ETC-only" value={plaza.hybrid_etc_only} />
          <ReadonlyField label="Shift pattern" value={plaza.shift_pattern} />
          <ReadonlyField label="Toll day cut-off" value={plaza.toll_day_cutoff} />
          <ReadonlyField label="O&M contractor" value={plaza.om_contractor} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Source & calendar</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <ReadonlyField
            label="Source — Daily TMS report"
            value={plaza.source_daily_tms_report}
          />
          <ReadonlyField
            label="Event calendar (holidays / mela window)"
            value={plaza.event_calendar}
          />
          <ReadonlyField label="Updated" value={formatLocalDateTime(plaza.updated_at)} />
        </CardContent>
      </Card>
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
