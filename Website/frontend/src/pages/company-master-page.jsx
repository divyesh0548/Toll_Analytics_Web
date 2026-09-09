import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { createCompany, getCompany, updateCompany } from '@/lib/api'
import { formatLocalDateTime } from '@/lib/utils'

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
  const [form, setForm] = useState(emptyForm)
  const [meta, setMeta] = useState({ created_at: null, updated_at: null })
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

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
    () => (isEdit ? 'Portfolio › Company master' : 'Portfolio › New company'),
    [isEdit],
  )

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function updateContact(index, key, value) {
    setForm((prev) => {
      const contacts = prev.contacts.map((contact, i) =>
        i === index ? { ...contact, [key]: value } : contact,
      )
      return { ...prev, contacts }
    })
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

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload = {
      ...form,
      contacts: form.contacts.filter((c) => c.name.trim()),
    }
    try {
      if (isEdit) {
        await updateCompany(companyIdentifier, payload)
      } else {
        await createCompany(payload)
      }
      navigate('/')
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
          <Field label="CIN">
            <Input value={form.cin} onChange={(e) => updateField('cin', e.target.value)} />
          </Field>
          <Field label="PAN">
            <Input value={form.pan} onChange={(e) => updateField('pan', e.target.value)} />
          </Field>
          <Field label="GSTIN">
            <Input value={form.gstin} onChange={(e) => updateField('gstin', e.target.value)} />
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
            <Input value={form.state} onChange={(e) => updateField('state', e.target.value)} />
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
            <CardDescription>People to reach for this company.</CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={addContact}>
            <Plus className="h-4 w-4" />
            Add
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {form.contacts.map((contact, index) => (
            <div key={index} className="space-y-3 rounded-sm border border-border p-4">
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
                  />
                </Field>
                <Field label="Phone">
                  <Input
                    value={contact.phone}
                    onChange={(e) => updateContact(index, 'phone', e.target.value)}
                  />
                </Field>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Separator />

      <div className="flex flex-wrap justify-end gap-3">
        <Button type="button" variant="outline" asChild>
          <Link to="/">Cancel</Link>
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Save company'}
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
