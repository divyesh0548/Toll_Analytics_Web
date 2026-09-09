import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '@/components/theme-provider'
import { AppShell } from '@/components/layout/app-shell'
import { PortfolioPage } from '@/pages/portfolio-page'
import { CompanyMasterPage } from '@/pages/company-master-page'

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<PortfolioPage />} />
            <Route path="companies/new" element={<CompanyMasterPage />} />
            <Route path="companies/:companyIdentifier" element={<CompanyMasterPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}
