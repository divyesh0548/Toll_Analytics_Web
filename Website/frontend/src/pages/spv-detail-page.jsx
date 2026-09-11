import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronDown, Pencil, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { getCompany, getSpv, listPlazas } from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

export function SpvDetailPage() {
  const { spvIdentifier } = useParams()
  const navigate = useNavigate()
  const [company, setCompany] = useState(null)
  const [spv, setSpv] = useState(null)
  const [plazas, setPlazas] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedPlaza, setSelectedPlaza] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [spvData, plazaData] = await Promise.all([
          getSpv(spvIdentifier),
          listPlazas(spvIdentifier),
        ])
        if (!active) return
        const companyData = await getCompany(spvData.company_identifier)
        if (!active) return
        setSpv(spvData)
        setCompany(companyData)
        setPlazas(plazaData.plazas || [])
      } catch (err) {
        if (active) setError(err.message || 'Failed to load SPV')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [spvIdentifier])

  const plazaOptions = useMemo(
    () =>
      plazas.map((plaza) => ({
        value: plaza.plaza_identifier,
        label: plaza.plaza_name,
      })),
    [plazas],
  )

  const companyIdentifier = spv?.company_identifier || company?.company_identifier

  function goToSelectedPlaza() {
    if (!selectedPlaza) return
    navigate(`/companies/spvs/plazas/${selectedPlaza}`)
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading SPV…</p>
  }

  if (error || !spv) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>SPV unavailable</CardTitle>
          <CardDescription>{error || 'SPV not found'}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <Link to={companyIdentifier ? `/companies/${companyIdentifier}` : '/portfolio'}>
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
            <Link to={`/companies/${companyIdentifier}`} className="hover:text-primary">
              {company?.company_name || 'Company'}
            </Link>{' '}
            › SPV
          </p>
          <h1 className="text-display">{spv.spv_name}</h1>
          <p className="text-body text-muted-foreground">
            {spv.project_stretch_name || 'Tollway SPV'}
            {spv.nh_no ? ` · NH ${spv.nh_no}` : ''}
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to={`/companies/spvs/${spvIdentifier}/edit`}>
            <Pencil className="h-4 w-4" />
            Edit SPV
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Plazas</CardTitle>
          <CardDescription>
            {plazas.length === 0
              ? 'No plazas linked yet. Create one under this SPV.'
              : 'Choose a plaza to open its details.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="relative w-full sm:max-w-md">
            <label className="mb-2 block text-small font-medium">Select plaza</label>
            <div className="relative">
              <select
                className={cn(
                  'flex h-10 w-full appearance-none rounded-sm border border-input bg-background py-2 pl-3 pr-10 text-body',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                value={selectedPlaza}
                onChange={(e) => setSelectedPlaza(e.target.value)}
                disabled={plazaOptions.length === 0}
              >
                <option value="">
                  {plazaOptions.length === 0 ? 'No plazas available' : 'Select plaza'}
                </option>
                {plazaOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <Button type="button" disabled={!selectedPlaza} onClick={goToSelectedPlaza}>
            Open plaza
          </Button>
          <Button asChild variant="outline">
            <Link to={`/companies/spvs/${spvIdentifier}/plazas/new`}>
              <Plus className="h-4 w-4" />
              New plaza
            </Link>
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Entity</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField label="Parent company" value={company?.company_name} />
          <ReadonlyField label="Project / stretch name" value={spv.project_stretch_name} />
          <ReadonlyField label="NH no." value={spv.nh_no} />
          <ReadonlyField label="Length (km)" value={spv.length_km} />
          <ReadonlyField label="Chainage from" value={spv.chainage_from} />
          <ReadonlyField label="Chainage to" value={spv.chainage_to} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tolling & rates</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField
            label="Rate notification no. / date"
            value={spv.rate_notification_no_date}
          />
          <ReadonlyField label="Annual revision %" value={spv.annual_revision_pct} />
          <ReadonlyField label="WPI linkage" value={spv.wpi_linkage} />
          <ReadonlyField label="Effective from" value={spv.effective_from} />
          <ReadonlyField label="Rate card upload" value={spv.rate_card_upload} />
          <div className="sm:col-span-2">
            <ReadonlyField
              label="Exempt categories policy"
              value={spv.exempt_categories_policy}
            />
          </div>
          <div className="sm:col-span-2">
            <ReadonlyField
              label="Local / monthly pass rules"
              value={spv.local_monthly_pass_rules}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Finance</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <ReadonlyField label="Lead bank / lender" value={spv.lead_bank_lender} />
          <ReadonlyField label="Facility & limit" value={spv.facility_limit} />
          <ReadonlyField label="Escrow bank" value={spv.escrow_bank} />
          <ReadonlyField
            label="Revenue share / premium %"
            value={spv.revenue_share_premium_pct}
          />
          <ReadonlyField label="Premium escalation" value={spv.premium_escalation} />
          <ReadonlyField label="Updated" value={formatLocalDateTime(spv.updated_at)} />
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
