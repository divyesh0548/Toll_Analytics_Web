import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { ThemeProvider } from '@/components/theme-provider'
import { AuthProvider } from '@/components/auth-provider'
import { ToastProvider } from '@/components/toast-provider'
import { ProtectedRoute } from '@/components/protected-route'
import { WriteProtectedRoute } from '@/components/write-protected-route'
import { AppShell } from '@/components/layout/app-shell'
import { LandingPage } from '@/pages/landing-page'
import { PortfolioPage } from '@/pages/portfolio-page'
import { CompanyMasterPage } from '@/pages/company-master-page'
import { CompanyDetailPage } from '@/pages/company-detail-page'
import { SpvMasterPage } from '@/pages/spv-master-page'
import { SpvDetailPage } from '@/pages/spv-detail-page'
import { PlazaMasterPage } from '@/pages/plaza-master-page'
import { PlazaDetailPage } from '@/pages/plaza-detail-page'
import { CreateUserPage } from '@/pages/create-user-page'

function LegacyPlazaDetailRedirect() {
  const { plazaIdentifier } = useParams()
  return <Navigate to={`/companies/spvs/plazas/${plazaIdentifier}`} replace />
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <ToastProvider>
            <Routes>
              <Route path="/" element={<LandingPage />} />

              <Route element={<ProtectedRoute />}>
                <Route element={<AppShell />}>
                  <Route element={<ProtectedRoute roles={['siteadmin']} />}>
                    <Route path="admin/users" element={<CreateUserPage />} />
                  </Route>

                  <Route element={<ProtectedRoute roles={['snt', 'viewer']} />}>
                    <Route path="portfolio" element={<PortfolioPage />} />

                    <Route element={<WriteProtectedRoute />}>
                      <Route path="companies/new" element={<CompanyMasterPage />} />
                      <Route path="companies/spvs/new" element={<SpvMasterPage />} />
                      <Route
                        path="companies/spvs/:spvIdentifier/edit"
                        element={<SpvMasterPage />}
                      />
                      <Route
                        path="companies/spvs/:spvIdentifier/plazas/new"
                        element={<PlazaMasterPage />}
                      />
                      <Route
                        path="companies/spvs/:spvIdentifier/plazas/:plazaIdentifier/edit"
                        element={<PlazaMasterPage />}
                      />
                      <Route
                        path="companies/:companyIdentifier/edit"
                        element={<CompanyMasterPage />}
                      />
                    </Route>

                    <Route
                      path="companies/spvs/plazas/:plazaIdentifier"
                      element={<PlazaDetailPage />}
                    />
                    <Route
                      path="companies/spvs/:spvIdentifier"
                      element={<SpvDetailPage />}
                    />
                    <Route
                      path="companies/spvs/:spvIdentifier/plazas/:plazaIdentifier"
                      element={<LegacyPlazaDetailRedirect />}
                    />
                    <Route path="companies/:companyIdentifier" element={<CompanyDetailPage />} />

                    <Route path="spvs/new" element={<Navigate to="/companies/spvs/new" replace />} />
                  </Route>
                </Route>
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </ToastProvider>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}
