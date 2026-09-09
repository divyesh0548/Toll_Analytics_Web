import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/components/auth-provider'

export function ProtectedRoute({ roles }) {
  const { user, loading, isAuthenticated } = useAuth()
  const location = useLocation()

  if (loading) {
    return <p className="text-body text-muted-foreground">Checking session…</p>
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />
  }

  if (roles?.length && !roles.includes(user.role)) {
    const fallback = user.role === 'siteadmin' ? '/admin/users' : '/portfolio'
    return <Navigate to={fallback} replace />
  }

  return <Outlet />
}
