import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronDown, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { useToast } from '@/components/toast-provider'
import { createCompany, getCompany, updateCompany } from '@/lib/api'
import {
  INDIAN_STATES,
  extractPanFromGstin,
  validateCin,
  validateCompanyContacts,
  validateGstin,
  validatePan,
} from '@/lib/company-validation'
import { cn, formatLocalDateTime } from '@/lib/utils'

const emptyContact = () => ({ name: '', email: '', phone: '' })

const emptyForm = () => ({
  company_name: '',
  short_code: '',
  cin: '',
  pan: '',
  gstin: '',
  address: '',
  state: '',
  city: '',
  pin: '',
  holding_parent: '',
  auditor: '',
  financial_year_end: '',
  contacts: [emptyContact()],
})

export function CompanyMasterPage() {
  const { companyIdentifier } = useParams()
  const isEdit = Boolean(companyIdentifier)
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [form, setForm] = useState(emptyForm)
  const [meta, setMeta] = useState({ created_at: null, updated_at: null })
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})

  useEffect(() => {
    if (!isEdit) return
    let active = true
    ;(async () => {
      try {
        const company = await getCompany(companyIdentifier)
        if (!active) return
        setForm({
          company_name: company.company_name || '',
          short_code: company.short_code || '',
          cin: company.cin || '',
          pan: company.pan || '',
          gstin: company.gstin || '',
          address: company.address || '',
          state: company.state || '',
          city: company.city || '',
          pin: company.pin || '',
          holding_parent: company.holding_parent || '',
          auditor: company.auditor || '',
          financial_year_end: company.financial_year_end || '',
          contacts:
            company.contacts?.length > 0
              ? company.contacts.map((c) => ({
                  name: c.name || '',
                  email: c.email || '',
                  phone: c.phone || '',
                }))
              : [emptyContact()],
        })
        setMeta({ created_at: company.created_at, updated_at: company.updated_at })
      } catch (err) {
        if (active) setError(err.message || 'Failed to load company')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [companyIdentifier, isEdit])

  const breadcrumb = useMemo(
    () => (isEdit ? 'Portfolio › Company › Edit' : 'Portfolio › New company'),
    [isEdit],
  )

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setFieldErrors((prev) => ({ ...prev, [key]: '' }))
  }

  function handleGstinChange(rawValue) {
    const gstin = rawValue.toUpperCase().replace(/[^0-9A-Z]/g, '').slice(0, 15)
    const pan = extractPanFromGstin(gstin)
    setForm((prev) => ({
      ...prev,
      gstin,
      pan: pan.length === 10 ? pan : prev.pan,
    }))
    setFieldErrors((prev) => ({ ...prev, gstin: '', pan: '' }))
  }

  function handlePanChange(rawValue) {
    const pan = rawValue.toUpperCase().replace(/[^0-9A-Z]/g, '').slice(0, 10)
    updateField('pan', pan)
  }

  function handleCinChange(rawValue) {
    const cin = rawValue.toUpperCase().replace(/[^0-9A-Z]/g, '').slice(0, 21)
    updateField('cin', cin)
  }

  function updateContact(index, key, value) {
    setForm((prev) => {
      const contacts = prev.contacts.map((contact, i) =>
        i === index ? { ...contact, [key]: value } : contact,
      )
      return { ...prev, contacts }
    })
    setFieldErrors((prev) => ({ ...prev, contacts: '' }))
  }

  function addContact() {
    setForm((prev) => ({ ...prev, contacts: [...prev.contacts, emptyContact()] }))
  }

  function removeContact(index) {
    setForm((prev) => {
      const contacts = prev.contacts.filter((_, i) => i !== index)
      return { ...prev, contacts: contacts.length ? contacts : [emptyContact()] }
    })
  }

  function resetForm() {
    if (isEdit) return
    setForm(emptyForm())
    setFieldErrors({})
    setError('')
  }

  function validateForm() {
    const nextErrors = {
      gstin: validateGstin(form.gstin),
      pan: validatePan(form.pan, { required: true }),
      cin: validateCin(form.cin),
      contacts: validateCompanyContacts(form.contacts),
    }

    if (form.gstin && form.pan) {
      const extracted = extractPanFromGstin(form.gstin)
      if (extracted && extracted !== form.pan.trim().toUpperCase()) {
        nextErrors.pan = 'PAN must match the PAN segment inside GSTIN'
      }
    }

    setFieldErrors(nextErrors)
    return !Object.values(nextErrors).some(Boolean)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!validateForm()) {
      setError('Please fix the highlighted validation errors.')
      return
    }

    setSaving(true)
    const payload = {
      ...form,
      gstin: form.gstin.trim().toUpperCase(),
      pan: form.pan.trim().toUpperCase(),
      cin: form.cin.trim().toUpperCase(),
      contacts: form.contacts.filter(
        (c) => c.name.trim() && (c.email.trim() || c.phone.trim()),
      ),
    }
    try {
      if (isEdit) {
        await updateCompany(companyIdentifier, payload)
        showToast('Company updated successfully')
        navigate(`/companies/${companyIdentifier}`)
      } else {
        const created = await createCompany(payload)
        showToast('Company created successfully')
        navigate(`/companies/${created.company_identifier}`)
      }
    } catch (err) {
      setError(err.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <p className="text-body text-muted-foreground">Loading company…</p>
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-small text-muted-foreground">{breadcrumb}</p>
          <h1 className="text-display">Company master</h1>
          <p className="text-body text-muted-foreground">
            Capture identity, registered office, group reporting, and key contacts.
          </p>
          {isEdit && (
            <p className="text-small text-muted-foreground">
              Created {formatLocalDateTime(meta.created_at)} · Updated{' '}
              {formatLocalDateTime(meta.updated_at)}
            </p>
          )}
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
          <CardTitle>Identity</CardTitle>
          <CardDescription>Legal and short identifiers for the company.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Company name" required>
            <Input
              value={form.company_name}
              onChange={(e) => updateField('company_name', e.target.value)}
              required
            />
          </Field>
          <Field label="Short code" required>
            <Input
              value={form.short_code}
              onChange={(e) => updateField('short_code', e.target.value)}
              required
            />
          </Field>
          <Field label="GSTIN" required error={fieldErrors.gstin}>
            <Input
              value={form.gstin}
              onChange={(e) => handleGstinChange(e.target.value)}
              placeholder="22AAAAA0000A1Z5"
              maxLength={15}
              required
            />
          </Field>
          <Field label="PAN" required error={fieldErrors.pan}>
            <Input
              value={form.pan}
              onChange={(e) => handlePanChange(e.target.value)}
              placeholder="Auto-filled from GSTIN"
              maxLength={10}
              required
            />
          </Field>
          <Field label="CIN" error={fieldErrors.cin}>
            <Input
              value={form.cin}
              onChange={(e) => handleCinChange(e.target.value)}
              placeholder="L12345MH2000PLC123456"
              maxLength={21}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Registered office</CardTitle>
          <CardDescription>Address used for statutory records.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label="Address">
              <Textarea
                value={form.address}
                onChange={(e) => updateField('address', e.target.value)}
              />
            </Field>
          </div>
          <Field label="State">
            <div className="relative">
              <select
                className={cn(
                  'flex h-10 w-full appearance-none rounded-sm border border-input bg-background py-2 pl-3 pr-10 text-body',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                value={form.state}
                onChange={(e) => updateField('state', e.target.value)}
              >
                <option value="">Select state</option>
                {INDIAN_STATES.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </Field>
          <Field label="City">
            <Input value={form.city} onChange={(e) => updateField('city', e.target.value)} />
          </Field>
          <Field label="PIN">
            <Input value={form.pin} onChange={(e) => updateField('pin', e.target.value)} />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Group & reporting</CardTitle>
          <CardDescription>Holding structure and audit calendar.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field label="Holding / parent">
            <Input
              value={form.holding_parent}
              onChange={(e) => updateField('holding_parent', e.target.value)}
            />
          </Field>
          <Field label="Auditor">
            <Input
              value={form.auditor}
              onChange={(e) => updateField('auditor', e.target.value)}
            />
          </Field>
          <Field label="Financial year end">
            <Input
              placeholder="e.g. 31-Mar"
              value={form.financial_year_end}
              onChange={(e) => updateField('financial_year_end', e.target.value)}
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div className="space-y-1.5">
            <CardTitle>Key contacts</CardTitle>
            <CardDescription>
              At least one contact with an email or phone is required.
            </CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={addContact}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </CardHeader>
        <CardContent className="space-y-5">
          {fieldErrors.contacts && (
            <p className="text-small text-destructive">{fieldErrors.contacts}</p>
          )}
          {form.contacts.map((contact, index) => (
            <div key={index} className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-subheader">Contact {index + 1}</p>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeContact(index)}
                  aria-label="Remove contact"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field label="Name">
                  <Input
                    value={contact.name}
                    onChange={(e) => updateContact(index, 'name', e.target.value)}
                  />
                </Field>
                <Field label="Email">
                  <Input
                    type="email"
                    value={contact.email}
                    onChange={(e) => updateContact(index, 'email', e.target.value)}
                    placeholder="name@example.com"
                  />
                </Field>
                <Field label="Phone">
                  <Input
                    value={contact.phone}
                    onChange={(e) => updateContact(index, 'phone', e.target.value)}
                    placeholder="10–15 digit phone"
                  />
                </Field>
              </div>
              {index < form.contacts.length - 1 && <Separator />}
            </div>
          ))}
        </CardContent>
      </Card>

      <Separator />

      <div className="flex flex-wrap justify-end gap-3">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create'}
        </Button>
      </div>
    </form>
  )
}

function Field({ label, required, error, children }) {
  return (
    <div className="space-y-2">
      <Label>
        {label}
        {required ? ' *' : ''}
      </Label>
      {children}
      {error ? <p className="text-small text-destructive">{error}</p> : null}
    </div>
  )
}
