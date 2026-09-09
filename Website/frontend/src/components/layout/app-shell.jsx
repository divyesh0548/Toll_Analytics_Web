import { Outlet } from 'react-router-dom'
import { Navbar } from '@/components/layout/navbar'

export function AppShell() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="content-shell py-8">
        <Outlet />
      </main>
    </div>
  )
}
