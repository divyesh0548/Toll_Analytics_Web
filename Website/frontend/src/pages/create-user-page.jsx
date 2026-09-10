import { useEffect, useState } from 'react'
import { ChevronDown, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/components/toast-provider'
import { createUser, listUsers } from '@/lib/api'
import { cn, formatLocalDateTime } from '@/lib/utils'

const ROLE_OPTIONS = [
  { value: 'snt', label: 'SNT' },
  { value: 'viewer', label: 'Viewer' },
]

const emptyForm = () => ({
  email: '',
  full_name: '',
  role: 'viewer',
})

export function CreateUserPage() {
  const { showToast } = useToast()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [form, setForm] = useState(emptyForm)

  async function loadUsers() {
    setLoading(true)
    try {
      const data = await listUsers()
      setUsers(data.users || [])
      setError('')
    } catch (err) {
      setError(err.message || 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadUsers()
  }, [])

  function openCreateDialog() {
    setForm(emptyForm())
    setFormError('')
    setShowCreateForm(true)
  }

  function closeCreateDialog() {
    setShowCreateForm(false)
    setFormError('')
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    setFormError('')
    try {
      await createUser(form)
      showToast('User created successfully')
      closeCreateDialog()
      await loadUsers()
    } catch (err) {
      setFormError(err.message || 'Could not create user')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="text-small uppercase tracking-[0.14em] text-muted-foreground">Site admin</p>
          <h1 className="text-display">Users</h1>
          <p className="text-body text-muted-foreground">
            Manage SNT and Viewer accounts. Temporary passwords are emailed automatically.
          </p>
        </div>
        <Button type="button" onClick={openCreateDialog}>
          <Plus className="h-4 w-4" />
          Create user
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>All users</CardTitle>
          <CardDescription>Accounts currently registered in the system.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-body text-muted-foreground">Loading users…</p>
          ) : users.length === 0 ? (
            <p className="text-body text-muted-foreground">No users yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] border-collapse text-left">
                <thead>
                  <tr className="border-b border-border text-small text-muted-foreground">
                    <th className="px-2 py-2 font-medium">Name</th>
                    <th className="px-2 py-2 font-medium">Email</th>
                    <th className="px-2 py-2 font-medium">Role</th>
                    <th className="px-2 py-2 font-medium">Active</th>
                    <th className="px-2 py-2 font-medium">Temp login</th>
                    <th className="px-2 py-2 font-medium">Email sent</th>
                    <th className="px-2 py-2 font-medium">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} className="border-b border-border/70 text-body">
                      <td className="px-2 py-2">{user.full_name || '—'}</td>
                      <td className="px-2 py-2">{user.email}</td>
                      <td className="px-2 py-2">{user.role}</td>
                      <td className="px-2 py-2">{user.is_active ? 'Yes' : 'No'}</td>
                      <td className="px-2 py-2">{user.temp_login ? 'Yes' : 'No'}</td>
                      <td className="px-2 py-2">{user.login_email_sent ? 'Yes' : 'No'}</td>
                      <td className="px-2 py-2">{formatLocalDateTime(user.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {error && <p className="mt-3 text-body text-destructive">{error}</p>}
        </CardContent>
      </Card>

      <Dialog
        open={showCreateForm}
        onClose={closeCreateDialog}
        title="Create user"
        description="Only SNT and Viewer roles can be created here."
      >
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={handleSubmit}>
          {formError && (
            <div className="sm:col-span-2 rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
              {formError}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="full_name">Full name</Label>
            <Input
              id="full_name"
              value={form.full_name}
              onChange={(e) => setForm((prev) => ({ ...prev, full_name: e.target.value }))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <div className="relative">
              <select
                id="role"
                className={cn(
                  'flex h-10 w-full appearance-none rounded-sm border border-input bg-background py-2 pl-3 pr-10 text-body',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                )}
                value={form.role}
                onChange={(e) => setForm((prev) => ({ ...prev, role: e.target.value }))}
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm((prev) => ({ ...prev, email: e.target.value }))}
            />
          </div>
          <div className="flex items-end justify-end gap-2 sm:col-span-2">
            <Button type="button" variant="outline" onClick={closeCreateDialog}>
              Close
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Creating…' : 'Create'}
            </Button>
          </div>
        </form>
      </Dialog>
    </section>
  )
}
