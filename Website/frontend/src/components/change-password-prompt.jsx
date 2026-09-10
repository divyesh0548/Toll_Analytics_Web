import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/ui/password-input'
import { useAuth } from '@/components/auth-provider'
import { useToast } from '@/components/toast-provider'

export function ChangePasswordPrompt() {
  const { passwordChangeOpen, dismissPasswordChange, changePassword } = useAuth()
  const { showToast } = useToast()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  function resetForm() {
    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
    setError('')
    setSaving(false)
  }

  function handleClose() {
    resetForm()
    dismissPasswordChange()
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match.')
      return
    }

    setSaving(true)
    try {
      await changePassword({ currentPassword, newPassword })
      showToast('Password updated successfully')
      resetForm()
    } catch (err) {
      setError(err.message || 'Could not update password')
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={passwordChangeOpen}
      onClose={handleClose}
      title="Change temporary password"
      description="You are signed in with a temporary password. You can update it now, or continue and change it later."
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        {error && (
          <div className="rounded-sm border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
            {error}
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="current-password">Current password</Label>
          <PasswordInput
            id="current-password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-password">New password</Label>
          <PasswordInput
            id="new-password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm-password">Confirm new password</Label>
          <PasswordInput
            id="confirm-password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
        </div>
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={handleClose} disabled={saving}>
            Not now
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Saving…' : 'Update password'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
