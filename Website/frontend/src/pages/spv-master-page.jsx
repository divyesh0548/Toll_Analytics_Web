import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { EntityBreadcrumb } from '@/components/entity-breadcrumb'
import { useToast } from '@/components/toast-provider'
import { createSpv, getSpv, listCompanies, updateSpv } from '@/lib/api'

const emptyForm = () => ({
  company_identifier: '',
  spv_name: '',
  project_stretch_name: '',
  nh_no: '',
  chainage_from: '',
  chainage_to: '',
  length_km: '',
  rate_notification_no_date: '',
  annual_revision_pct: '',
  wpi_linkage: '',
  effective_from: '',
  rate_card_upload: '',
  exempt_categories_policy: '',
  local_monthly_pass_rules: '',
  lead_bank_lender: '',
  facility_limit: '',
  escrow_bank: '',
  revenue_share_premium_pct: '',
  premium_escalation: '',
})

function toForm(spv) {
  return {
    company_identifier: spv.company_identifier || '',
    spv_name: spv.spv_name || '',
    project_stretch_name: spv.project_stretch_name || '',
    nh_no: spv.nh_no || '',
    chainage_from: spv.chainage_from || '',
    chainage_to: spv.chainage_to || '',
    length_km: spv.length_km ?? '',
    rate_notification_no_date: spv.rate_notification_no_date || '',
    annual_revision_pct: spv.annual_revision_pct ?? '',
    wpi_linkage: spv.wpi_linkage || '',
    effective_from: spv.effective_from || '',
    rate_card_upload: spv.rate_card_upload || '',
    exempt_categories_policy: spv.exempt_categories_policy || '',
    local_monthly_pass_rules: spv.local_monthly_pass_rules || '',
    lead_bank_lender: spv.lead_bank_lender || '',
    facility_limit: spv.facility_limit || '',
    escrow_bank: spv.escrow_bank || '',
    revenue_share_premium_pct: spv.revenue_share_premium_pct ?? '',
    premium_escalation: spv.premium_escalation || '',
  }
}

export function SpvMasterPage() {
  const navigate = useNavigate()
  const { spvIdentifier } = useParams()
  const [searchParams] = useSearchParams()
  const companyFromQuery = searchParams.get('company') || ''
  const isEdit = Boolean(spvIdentifier)
  const { showToast } = useToast()
  const [companies, setCompanies] = useState([])
  const [spvName, setSpvName] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const companyData = await listCompanies()
        if (!active) return
        setCompanies(companyData.companies || [])

        if (isEdit) {
          const spv = await getSpv(spvIdentifier)
          if (!active) return
          setForm(toForm(spv))
          setSpvName(spv.spv_name || '')
        } else if (companyFromQuery) {
          setForm((prev) => ({ ...prev, company_identifier: companyFromQuery }))
        }
      } catch (err) {
        if (active) setError(err.message || 'Failed to load SPV form')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [companyFromQuery, spvIdentifier, isEdit])

  const companyOptions = useMemo(
    () =>
      companies.map((company) => ({
        value: company.company_identifier,
        label: company.company_name,
        meta: company.short_code,
      })),
    [companies],
  )

  const selectedCompany = useMemo(
    () => companies.find((c) => c.company_identifier === form.company_identifier),
    [companies, form.company_identifier],
  )

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function resetForm() {
    if (isEdit) return
    setForm(emptyForm())
    setError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!form.company_identifier) {
      setError('Select a parent company.')
      return
    }
    if (!form.spv_name.trim()) {
      setError('SPV name is required.')
      return
    }
    if (form.length_km !== '' && !/^\d+$/.test(String(form.length_km).trim())) {
      setError('Length (km) must be an integer.')
      return
    }

    const payload = {
      ...form,
      length_km: form.length_km === '' ? null : Number(form.length_km),
      annual_revision_pct:
        form.annual_revision_pct === '' ? null : Number(form.annual_revision_pct),
      revenue_share_premium_pct:
        form.revenue_share_premium_pct === ''
          ? null
          : Number(form.revenue_share_premium_pct),
    }

    setSaving(true)
    try {
      if (isEdit) {
        await updateSpv(spvIdentifier, payload)
        showToast('SPV updated successfully')
        navigate(`/companies/spvs/${spvIdentifier}`)
      } else {
        const created = await createSpv(payload)
        showToast('SPV created successfully')
        navigate(`/companies/spvs/${created.spv_identifier}`)
      }
    } catch (err) {
      setError(err.message || 'Could not save SPV')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading SPV form…</p>
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <EntityBreadcrumb
            items={
              isEdit
                ? [
                    { label: 'Portfolio', to: '/portfolio' },
                    {
                      label: selectedCompany?.company_name || 'Company',
                      to: form.company_identifier
                        ? `/companies/${form.company_identifier}`
                        : undefined,
                    },
                    {
                      label: spvName || form.spv_name || 'SPV',
                      to: `/companies/spvs/${spvIdentifier}`,
                    },
                    { label: 'Edit' },
                  ]
                : [
                    { label: 'Portfolio', to: '/portfolio' },
                    ...(form.company_identifier
                      ? [
                          {
                            label: selectedCompany?.company_name || 'Company',
                            to: `/companies/${form.company_identifier}`,
                          },
                        ]
                      : []),
                    { label: 'New SPV' },
                  ]
            }
          />
          <h1 className="text-display">{isEdit ? 'Edit SPV' : 'SPV master'}</h1>
          <p className="mt-1 text-body text-muted-foreground">
            {isEdit
              ? 'Update tollway SPV details.'
              : 'Create a tollway SPV under an existing company. Plaza setup comes later.'}
          </p>
        </div>
        {!isEdit && (
          <Button type="button" variant="outline" onClick={resetForm}>
            <RotateCcw className="h-4 w-4" />
            Reset
          </Button>
        )}
      </div>

      {error && (
        <div className="rounded-sm border border-destructive/40 bg-destructive/10 px-4 py-3 text-body text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Entity</CardTitle>
          <CardDescription>Link this SPV to its parent company.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Parent company" required>
            <SearchableSelect
              options={companyOptions}
              value={form.company_identifier}
              onChange={(value) => updateField('company_identifier', value)}
              placeholder={companyOptions.length ? 'Search company' : 'No companies'}
              searchPlaceholder="Search by name or short code"
              emptyText="No companies found"
              disabled={companyOptions.length === 0}
            />
          </Field>
          <Field label="SPV name" required>
            <Input
              value={form.spv_name}
              onChange={(e) => updateField('spv_name', e.target.value)}
              required
            />
          </Field>
          <Field label="Project / stretch name">
            <Input
              value={form.project_stretch_name}
              onChange={(e) => updateField('project_stretch_name', e.target.value)}
            />
          </Field>
          <Field label="NH no.">
            <Input value={form.nh_no} onChange={(e) => updateField('nh_no', e.target.value)} />
          </Field>
          <Field label="Chainage from">
            <Input
              value={form.chainage_from}
              onChange={(e) => updateField('chainage_from', e.target.value)}
            />
          </Field>
          <Field label="Chainage to">
            <Input
              value={form.chainage_to}
              onChange={(e) => updateField('chainage_to', e.target.value)}
            />
          </Field>
          <Field label="Length (km)">
            <Input
              type="number"
              inputMode="numeric"
              step="1"
              min="0"
              value={form.length_km}
              onChange={(e) => updateField('length_km', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tolling & rates</CardTitle>
          <CardDescription>Notification, revision, and rate-card details.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Rate notification no. / date">
            <Input
              value={form.rate_notification_no_date}
              onChange={(e) => updateField('rate_notification_no_date', e.target.value)}
            />
          </Field>
          <Field label="Annual revision %">
            <Input
              type="number"
              step="0.01"
              value={form.annual_revision_pct}
              onChange={(e) => updateField('annual_revision_pct', e.target.value)}
            />
          </Field>
          <Field label="WPI linkage">
            <Input
              value={form.wpi_linkage}
              onChange={(e) => updateField('wpi_linkage', e.target.value)}
            />
          </Field>
          <Field label="Effective from">
            <Input
              type="date"
              value={form.effective_from}
              onChange={(e) => updateField('effective_from', e.target.value)}
            />
          </Field>
          <Field label="Rate card upload">
            <Input
              value={form.rate_card_upload}
              onChange={(e) => updateField('rate_card_upload', e.target.value)}
              placeholder="Rate card reference / path"
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Exempt categories policy">
              <Textarea
                value={form.exempt_categories_policy}
                onChange={(e) => updateField('exempt_categories_policy', e.target.value)}
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label="Local / monthly pass rules">
              <Textarea
                value={form.local_monthly_pass_rules}
                onChange={(e) => updateField('local_monthly_pass_rules', e.target.value)}
              />
            </Field>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Finance</CardTitle>
          <CardDescription>Lender, escrow, and premium terms.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Lead bank / lender">
            <Input
              value={form.lead_bank_lender}
              onChange={(e) => updateField('lead_bank_lender', e.target.value)}
            />
          </Field>
          <Field label="Facility & limit">
            <Input
              value={form.facility_limit}
              onChange={(e) => updateField('facility_limit', e.target.value)}
            />
          </Field>
          <Field label="Escrow bank">
            <Input
              value={form.escrow_bank}
              onChange={(e) => updateField('escrow_bank', e.target.value)}
            />
          </Field>
          <Field label="Revenue share / premium %">
            <Input
              type="number"
              step="0.01"
              value={form.revenue_share_premium_pct}
              onChange={(e) => updateField('revenue_share_premium_pct', e.target.value)}
            />
          </Field>
          <Field label="Premium escalation">
            <Input
              value={form.premium_escalation}
              onChange={(e) => updateField('premium_escalation', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Separator />

      <div className="flex justify-end">
        <Button type="submit" disabled={saving || companyOptions.length === 0}>
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create'}
        </Button>
      </div>
    </form>
  )
}

function Field({ label, required, children }) {
  return (
    <div className="space-y-2">
      <Label>
        {label}
        {required ? ' *' : ''}
      </Label>
      {children}
    </div>
  )
}
