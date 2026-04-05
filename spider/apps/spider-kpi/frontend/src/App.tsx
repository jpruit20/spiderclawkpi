import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'
import { CommercialPerformance } from './pages/CommercialPerformance'
import { DiagnosticsPage } from './pages/Diagnostics'
import { ExecutiveOverview } from './pages/ExecutiveOverview'
import { IssueRadar } from './pages/IssueRadar'
import { SourceHealthPage } from './pages/SourceHealth'
import { SupportCX } from './pages/SupportCX'

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ErrorBoundary label="Executive Overview"><ExecutiveOverview /></ErrorBoundary>} />
        <Route path="/commercial" element={<ErrorBoundary label="Commercial Performance"><CommercialPerformance /></ErrorBoundary>} />
        <Route path="/support" element={<ErrorBoundary label="Support / CX"><SupportCX /></ErrorBoundary>} />
        <Route path="/issues" element={<ErrorBoundary label="Issue Radar"><IssueRadar /></ErrorBoundary>} />
        <Route path="/diagnostics" element={<ErrorBoundary label="Diagnostics"><DiagnosticsPage /></ErrorBoundary>} />
        <Route path="/source-health" element={<ErrorBoundary label="Source Health"><SourceHealthPage /></ErrorBoundary>} />
      </Routes>
    </Layout>
  )
}
