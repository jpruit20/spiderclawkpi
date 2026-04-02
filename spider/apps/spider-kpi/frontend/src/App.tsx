import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
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
        <Route path="/" element={<ExecutiveOverview />} />
        <Route path="/commercial" element={<CommercialPerformance />} />
        <Route path="/support" element={<SupportCX />} />
        <Route path="/issues" element={<IssueRadar />} />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
        <Route path="/source-health" element={<SourceHealthPage />} />
      </Routes>
    </Layout>
  )
}
