import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronDown, Pencil, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityBreadcrumb } from '@/components/entity-breadcrumb'
import { getCompany, listSpvs } from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

export function CompanyDetailPage() {
  const { companyIdentifier } = useParams()
  const navigate = useNavigate()
  const [company, setCompany] = useState(null)
  const [spvs, setSpvs] = useState([])
  const [selectedSpv, setSelectedSpv] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const [companyData, spvData] = await Promise.all([
          getCompany(companyIdentifier),
          listSpvs(companyIdentifier),
        ])
        if (!active) return
        setCompany(companyData)
        setSpvs(spvData.spvs || [])
      } catch (err) {
        if (active) setError(err.message || 'Failed to load company')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [companyIdentifier])

  const spvOptions = useMemo(
    () =>
      spvs.map((spv) => ({
        value: spv.spv_identifier,
        label: spv.spv_name,
      })),
    [spvs],
  )

  function goToSelectedSpv() {
    if (!selectedSpv) return
    navigate(`/companies/spvs/${selectedSpv}`)
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading company…</p>
  }

  if (error || !company) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Company unavailable</CardTitle>
          <CardDescription>{error || 'Company not found'}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="outline">
            <Link to="/portfolio">Back to portfolio</Link>
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
              { label: company.company_name },
            ]}
          />
          <h1 className="text-display">{company.company_name}</h1>
          <p className="mt-1 text-body text-muted-foreground">
            {company.short_code}
            {company.city ? ` · ${company.city}` : ''}
            {company.state ? `, ${company.state}` : ''}
          </p>
        </div>
        <Button asChild variant="outline">
          <Link to={`/companies/${companyIdentifier}/edit`}>
            <Pencil className="h-4 w-4" />
            Edit company
          </Link>
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Company info</CardTitle>
            <CardDescription>Master data and hierarchy counts.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <ReadonlyField label="SPVs" value={company.spv_count ?? spvs.length} />
            <ReadonlyField label="Plazas" value={company.plaza_count ?? 0} />
            <ReadonlyField label="GSTIN" value={company.gstin} />
            <ReadonlyField label="PAN" value={company.pan} />
            <ReadonlyField label="CIN" value={company.cin} />
            <ReadonlyField label="Holding / parent" value={company.holding_parent} />
            <ReadonlyField label="Auditor" value={company.auditor} />
            <ReadonlyField label="Financial year end" value={company.financial_year_end} />
            <div className="sm:col-span-2">
              <ReadonlyField label="Address" value={company.address} />
            </div>
            <ReadonlyField label="Updated" value={formatLocalDateTime(company.updated_at)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Contacts</CardTitle>
            <CardDescription>People linked to this company.</CardDescription>
          </CardHeader>
          <CardContent>
            {!company.contacts?.length ? (
              <p className="text-body text-muted-foreground">No contacts on file.</p>
            ) : (
              <div className="space-y-3">
                <div className="grid gap-1 border-b border-border pb-2 sm:grid-cols-3">
                  <p className="text-small font-medium text-muted-foreground">Name</p>
                  <p className="text-small font-medium text-muted-foreground">Email</p>
                  <p className="text-small font-medium text-muted-foreground">Phone</p>
                </div>
                {company.contacts.map((contact) => (
                  <div
                    key={contact.id || contact.email}
                    className="grid gap-1 sm:grid-cols-3"
                  >
                    <p className="text-body font-medium">{contact.name || '—'}</p>
                    <p className="text-body text-muted-foreground">{contact.email || '—'}</p>
                    <p className="text-body text-muted-foreground">{contact.phone || '—'}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>SPVs</CardTitle>
          <CardDescription>
            {spvs.length === 0
              ? 'No SPVs linked yet. Create one to continue the hierarchy.'
              : 'Choose an SPV to open its details.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="relative w-full sm:max-w-md">
            <label className="mb-2 block text-small font-medium">Select SPV</label>
            <div className="relative">
              <select
                className={cn(
                  'flex h-10 w-full appearance-none rounded-sm border border-input bg-background py-2 pl-3 pr-10 text-body',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                value={selectedSpv}
                onChange={(e) => setSelectedSpv(e.target.value)}
                disabled={spvOptions.length === 0}
              >
                <option value="">
                  {spvOptions.length === 0 ? 'No SPVs available' : 'Select SPV'}
                </option>
                {spvOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <Button type="button" disabled={!selectedSpv} onClick={goToSelectedSpv}>
            Open SPV
          </Button>
          <Button asChild variant="outline">
            <Link to={`/companies/spvs/new?company=${companyIdentifier}`}>
              <Plus className="h-4 w-4" />
              New SPV
            </Link>
          </Button>
        </CardContent>
      </Card>
    </section>
  )
}

function ReadonlyField({ label, value }) {
  return (
    <div className="space-y-1">
      <p className="text-small text-muted-foreground">{label}</p>
      <p className="text-body">{value ?? '—'}</p>
    </div>
  )
}
