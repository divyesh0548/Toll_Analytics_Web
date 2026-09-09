import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '@/components/theme-provider'
import { AuthProvider } from '@/components/auth-provider'
import { ProtectedRoute } from '@/components/protected-route'
import { AppShell } from '@/components/layout/app-shell'
import { LandingPage } from '@/pages/landing-page'
import { PortfolioPage } from '@/pages/portfolio-page'
import { CompanyMasterPage } from '@/pages/company-master-page'
import { SpvMasterPage } from '@/pages/spv-master-page'
import { CreateUserPage } from '@/pages/create-user-page'

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />

            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route element={<ProtectedRoute roles={['siteadmin']} />}>
                  <Route path="admin/users" element={<CreateUserPage />} />
                </Route>

                <Route element={<ProtectedRoute roles={['snt', 'viewer']} />}>
                  <Route path="portfolio" element={<PortfolioPage />} />
                  <Route path="companies/new" element={<CompanyMasterPage />} />
                  <Route path="companies/:companyIdentifier" element={<CompanyMasterPage />} />
                  <Route path="spvs/new" element={<SpvMasterPage />} />
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}
