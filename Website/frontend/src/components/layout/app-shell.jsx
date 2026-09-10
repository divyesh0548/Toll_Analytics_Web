import { Outlet } from 'react-router-dom'
import { Navbar } from '@/components/layout/navbar'
import { ChangePasswordPrompt } from '@/components/change-password-prompt'

export function AppShell() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="content-shell py-8">
        <Outlet />
      </main>
      <ChangePasswordPrompt />
    </div>
  )
}
