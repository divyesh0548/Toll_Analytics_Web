import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { EntityBreadcrumb } from '@/components/entity-breadcrumb'
import { useToast } from '@/components/toast-provider'
import { createPlaza, getCompany, getPlaza, getSpv, updatePlaza } from '@/lib/api'

const emptyForm = () => ({
  spv_identifier: '',
  plaza_name: '',
  plaza_code: '',
  chainage: '',
  district_state: '',
  latitude: '',
  longitude: '',
  tolling_start_date: '',
  total_lanes: '',
  lhs_rhs_split: '',
  hybrid_etc_only: '',
  shift_pattern: '',
  toll_day_cutoff: '',
  om_contractor: '',
  source_daily_tms_report: '',
  event_calendar: '',
})

function toForm(plaza) {
  return {
    spv_identifier: plaza.spv_identifier || '',
    plaza_name: plaza.plaza_name || '',
    plaza_code: plaza.plaza_code || '',
    chainage: plaza.chainage || '',
    district_state: plaza.district_state || '',
    latitude: plaza.latitude || '',
    longitude: plaza.longitude || '',
    tolling_start_date: plaza.tolling_start_date || '',
    total_lanes: plaza.total_lanes ?? '',
    lhs_rhs_split: plaza.lhs_rhs_split || '',
    hybrid_etc_only: plaza.hybrid_etc_only || '',
    shift_pattern: plaza.shift_pattern || '',
    toll_day_cutoff: plaza.toll_day_cutoff || '',
    om_contractor: plaza.om_contractor || '',
    source_daily_tms_report: plaza.source_daily_tms_report || '',
    event_calendar: plaza.event_calendar || '',
  }
}

export function PlazaMasterPage() {
  const navigate = useNavigate()
  const { spvIdentifier: spvFromParams, plazaIdentifier } = useParams()
  const isEdit = Boolean(plazaIdentifier)
  const { showToast } = useToast()
  const [company, setCompany] = useState(null)
  const [spvIdentifier, setSpvIdentifier] = useState(spvFromParams || '')
  const [spvName, setSpvName] = useState('')
  const [plazaName, setPlazaName] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        if (isEdit) {
          const plaza = await getPlaza(plazaIdentifier)
          if (!active) return
          const spv = await getSpv(plaza.spv_identifier)
          if (!active) return
          const companyData = await getCompany(spv.company_identifier)
          if (!active) return
          setForm(toForm(plaza))
          setSpvIdentifier(plaza.spv_identifier)
          setSpvName(spv.spv_name || '')
          setPlazaName(plaza.plaza_name || '')
          setCompany(companyData)
        } else {
          const spv = await getSpv(spvFromParams)
          if (!active) return
          const companyData = await getCompany(spv.company_identifier)
          if (!active) return
          setSpvIdentifier(spvFromParams)
          setSpvName(spv.spv_name || '')
          setCompany(companyData)
          setForm((prev) => ({ ...prev, spv_identifier: spvFromParams }))
        }
      } catch (err) {
        if (active) setError(err.message || 'Failed to load plaza form')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [spvFromParams, plazaIdentifier, isEdit])

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function resetForm() {
    if (isEdit) return
    setForm({ ...emptyForm(), spv_identifier: spvIdentifier })
    setError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!form.plaza_name.trim()) {
      setError('Plaza name is required.')
      return
    }
    if (form.total_lanes !== '' && !/^\d+$/.test(String(form.total_lanes).trim())) {
      setError('Total lanes must be an integer.')
      return
    }

    const payload = {
      ...form,
      spv_identifier: spvIdentifier,
      total_lanes: form.total_lanes === '' ? null : Number(form.total_lanes),
    }

    setSaving(true)
    try {
      if (isEdit) {
        await updatePlaza(plazaIdentifier, payload)
        showToast('Plaza updated successfully')
        navigate(`/companies/spvs/plazas/${plazaIdentifier}`)
      } else {
        const created = await createPlaza(payload)
        showToast('Plaza created successfully')
        navigate(`/companies/spvs/plazas/${created.plaza_identifier}`)
      }
    } catch (err) {
      setError(err.message || 'Could not save plaza')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading plaza form…</p>
  }

  const companyIdentifier = company?.company_identifier
  const breadcrumbItems = [
    { label: 'Portfolio', to: '/portfolio' },
    {
      label: company?.company_name || 'Company',
      to: companyIdentifier ? `/companies/${companyIdentifier}` : undefined,
    },
    {
      label: spvName || 'SPV',
      to: spvIdentifier ? `/companies/spvs/${spvIdentifier}` : undefined,
    },
  ]
  if (isEdit) {
    breadcrumbItems.push({
      label: plazaName || form.plaza_name || 'Plaza',
      to: `/companies/spvs/plazas/${plazaIdentifier}`,
    })
    breadcrumbItems.push({ label: 'Edit' })
  } else {
    breadcrumbItems.push({ label: 'New plaza' })
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <EntityBreadcrumb items={breadcrumbItems} />
          <h1 className="text-display">{isEdit ? 'Edit plaza' : 'Plaza master'}</h1>
          <p className="mt-1 text-body text-muted-foreground">
            {spvName
              ? `Parent SPV: ${spvName}`
              : 'Capture plaza identity and operations details.'}
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
          <CardTitle>Identity & location</CardTitle>
          <CardDescription>Name, code, chainage, and geography.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Plaza name" required>
            <Input
              value={form.plaza_name}
              onChange={(e) => updateField('plaza_name', e.target.value)}
              required
            />
          </Field>
          <Field label="Plaza code">
            <Input
              value={form.plaza_code}
              onChange={(e) => updateField('plaza_code', e.target.value)}
            />
          </Field>
          <Field label="Chainage">
            <Input
              value={form.chainage}
              onChange={(e) => updateField('chainage', e.target.value)}
            />
          </Field>
          <Field label="District / state">
            <Input
              value={form.district_state}
              onChange={(e) => updateField('district_state', e.target.value)}
            />
          </Field>
          <Field label="Latitude">
            <Input
              value={form.latitude}
              onChange={(e) => updateField('latitude', e.target.value)}
            />
          </Field>
          <Field label="Longitude">
            <Input
              value={form.longitude}
              onChange={(e) => updateField('longitude', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operations</CardTitle>
          <CardDescription>Lanes, tolling mode, shifts, and cut-off.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Tolling start date">
            <Input
              type="date"
              value={form.tolling_start_date}
              onChange={(e) => updateField('tolling_start_date', e.target.value)}
            />
          </Field>
          <Field label="Total lanes">
            <Input
              type="number"
              inputMode="numeric"
              step="1"
              min="0"
              value={form.total_lanes}
              onChange={(e) => updateField('total_lanes', e.target.value)}
            />
          </Field>
          <Field label="LHS / RHS split">
            <Input
              value={form.lhs_rhs_split}
              onChange={(e) => updateField('lhs_rhs_split', e.target.value)}
              placeholder="e.g. 3/3"
            />
          </Field>
          <Field label="Hybrid / ETC-only">
            <Input
              value={form.hybrid_etc_only}
              onChange={(e) => updateField('hybrid_etc_only', e.target.value)}
              placeholder="Hybrid or ETC-only"
            />
          </Field>
          <Field label="Shift pattern">
            <Input
              value={form.shift_pattern}
              onChange={(e) => updateField('shift_pattern', e.target.value)}
            />
          </Field>
          <Field label="Toll day cut-off">
            <Input
              value={form.toll_day_cutoff}
              onChange={(e) => updateField('toll_day_cutoff', e.target.value)}
              placeholder="e.g. 06:00"
            />
          </Field>
          <Field label="O&M contractor">
            <Input
              value={form.om_contractor}
              onChange={(e) => updateField('om_contractor', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Source & calendar</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <Field label="Source — Daily TMS report">
            <Textarea
              value={form.source_daily_tms_report}
              onChange={(e) => updateField('source_daily_tms_report', e.target.value)}
            />
          </Field>
          <Field label="Event calendar (holidays / mela window)">
            <Textarea
              value={form.event_calendar}
              onChange={(e) => updateField('event_calendar', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Separator />

      <div className="flex justify-end">
        <Button type="submit" disabled={saving}>
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
