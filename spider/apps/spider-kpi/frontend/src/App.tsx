import { Suspense, lazy } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ExecutiveOverview } from './pages/ExecutiveOverview'

const CommercialPerformance = lazy(() => import('./pages/CommercialPerformance').then((m) => ({ default: m.CommercialPerformance })))
const DiagnosticsPage = lazy(() => import('./pages/Diagnostics').then((m) => ({ default: m.DiagnosticsPage })))
const IssueRadar = lazy(() => import('./pages/IssueRadar').then((m) => ({ default: m.IssueRadar })))
const SourceHealthPage = lazy(() => import('./pages/SourceHealth').then((m) => ({ default: m.SourceHealthPage })))
const SupportCX = lazy(() => import('./pages/SupportCX').then((m) => ({ default: m.SupportCX })))
const UXBehavior = lazy(() => import('./pages/UXBehavior').then((m) => ({ default: m.UXBehavior })))

function withBoundary(label: string, node: React.ReactNode) {
  return (
    <ErrorBoundary label={label}>
      <Suspense fallback={<div className="card"><div className="card-title">Loading</div><div className="state-message">Loading {label}…</div></div>}>
        {node}
      </Suspense>
    </ErrorBoundary>
  )
}

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ErrorBoundary label="Executive Overview"><ExecutiveOverview /></ErrorBoundary>} />
        <Route path="/commercial" element={withBoundary('Commercial Performance', <CommercialPerformance />)} />
        <Route path="/support" element={withBoundary('Support / CX', <SupportCX />)} />
        <Route path="/ux" element={withBoundary('Website UX / Behavior', <UXBehavior />)} />
        <Route path="/issues" element={withBoundary('Issue Radar', <IssueRadar />)} />
        <Route path="/diagnostics" element={withBoundary('Diagnostics', <DiagnosticsPage />)} />
        <Route path="/source-health" element={withBoundary('Source Health', <SourceHealthPage />)} />
      </Routes>
    </Layout>
  )
}
