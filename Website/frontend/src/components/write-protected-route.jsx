import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/components/auth-provider'
import { useToast } from '@/components/toast-provider'

const READ_ONLY_MESSAGE = 'Account is limited to read-only access'

function writeFallback(pathname) {
  if (pathname.endsWith('/edit')) {
    return pathname.replace(/\/edit$/, '') || '/portfolio'
  }
  if (pathname.endsWith('/plazas/new')) {
    return pathname.replace(/\/plazas\/new$/, '') || '/portfolio'
  }
  if (pathname === '/companies/new' || pathname === '/companies/spvs/new' || pathname === '/spvs/new') {
    return '/portfolio'
  }
  return '/portfolio'
}

function ReadOnlyRedirect({ from }) {
  const { showToast } = useToast()

  useEffect(() => {
    showToast(READ_ONLY_MESSAGE, 'warning')
  }, [from, showToast])

  return <Navigate to={writeFallback(from)} replace />
}

/** Blocks create/edit pages for viewers; shows a warning toast instead. */
export function WriteProtectedRoute() {
  const { canWrite } = useAuth()
  const location = useLocation()

  if (!canWrite) {
    return <ReadOnlyRedirect from={location.pathname} />
  }

  return <Outlet />
}

export { READ_ONLY_MESSAGE }
