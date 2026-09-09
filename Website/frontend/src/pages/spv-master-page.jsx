import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { SearchableSelect } from '@/components/ui/searchable-select'
import { createSpv, listCompanies } from '@/lib/api'

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

export function SpvMasterPage() {
  const navigate = useNavigate()
  const [companies, setCompanies] = useState([])
  const [form, setForm] = useState(emptyForm)
  const [loadingCompanies, setLoadingCompanies] = useState(true)
  const [saving, setSaving] = useState(false)
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
        if (active) setLoadingCompanies(false)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const companyOptions = useMemo(
    () =>
      companies.map((company) => ({
        value: company.company_identifier,
        label: company.company_name,
        meta: company.short_code,
      })),
    [companies],
  )

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function resetForm() {
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

    setSaving(true)
    try {
      await createSpv({
        ...form,
        length_km: form.length_km === '' ? null : Number(form.length_km),
        annual_revision_pct:
          form.annual_revision_pct === '' ? null : Number(form.annual_revision_pct),
        revenue_share_premium_pct:
          form.revenue_share_premium_pct === ''
            ? null
            : Number(form.revenue_share_premium_pct),
      })
      navigate('/portfolio')
    } catch (err) {
      setError(err.message || 'Could not create SPV')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-small text-muted-foreground">Portfolio › New SPV</p>
          <h1 className="text-display">SPV master</h1>
          <p className="text-body text-muted-foreground">
            Create a tollway SPV under an existing company. Plaza setup comes later.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={resetForm}>
          <RotateCcw className="h-4 w-4" />
          Reset
        </Button>
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
              placeholder={loadingCompanies ? 'Loading companies…' : 'Search company'}
              searchPlaceholder="Search by name or short code"
              emptyText="No companies found"
              disabled={loadingCompanies || companyOptions.length === 0}
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
              type="file"
              onChange={(e) =>
                updateField('rate_card_upload', e.target.files?.[0]?.name || '')
              }
            />
            {form.rate_card_upload ? (
              <p className="text-small text-muted-foreground">Selected: {form.rate_card_upload}</p>
            ) : null}
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
          {saving ? 'Saving…' : 'Create'}
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
