import { Suspense, lazy } from 'react'
import { Navigate, Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AuthGate } from './components/AuthGate'

const CommandCenter = lazy(() => import('./pages/CommandCenter').then((m) => ({ default: m.CommandCenter })))
const CustomerExperienceDivision = lazy(() => import('./pages/CustomerExperienceDivision').then((m) => ({ default: m.CustomerExperienceDivision })))
const MarketingDivision = lazy(() => import('./pages/MarketingDivision').then((m) => ({ default: m.MarketingDivision })))
const ProductEngineeringDivision = lazy(() => import('./pages/ProductEngineeringDivision').then((m) => ({ default: m.ProductEngineeringDivision })))
const OperationsDivision = lazy(() => import('./pages/OperationsDivision').then((m) => ({ default: m.OperationsDivision })))
const ProductionManufacturingDivision = lazy(() => import('./pages/ProductionManufacturingDivision').then((m) => ({ default: m.ProductionManufacturingDivision })))
const DepartmentViews = lazy(() => import('./pages/DepartmentViews').then((m) => ({ default: m.DepartmentViews })))
const RevenueEngine = lazy(() => import('./pages/RevenueEngine').then((m) => ({ default: m.RevenueEngine })))
const FrictionMap = lazy(() => import('./pages/FrictionMap').then((m) => ({ default: m.FrictionMap })))
const IssueRadar = lazy(() => import('./pages/IssueRadar').then((m) => ({ default: m.IssueRadar })))
const RootCause = lazy(() => import('./pages/RootCause').then((m) => ({ default: m.RootCause })))
const SystemHealthPage = lazy(() => import('./pages/SystemHealth').then((m) => ({ default: m.SystemHealthPage })))
const SocialIntelligence = lazy(() => import('./pages/SocialIntelligence').then((m) => ({ default: m.SocialIntelligence })))
const Deci = lazy(() => import('./pages/Deci').then((m) => ({ default: m.Deci })))
const TelemetryAnalysisPage = lazy(() => import('./pages/TelemetryAnalysisPage').then((m) => ({ default: m.TelemetryAnalysisPage })))
const LoreLedger = lazy(() => import('./pages/LoreLedger').then((m) => ({ default: m.LoreLedger })))

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
    <AuthGate>
      <Layout>
        <Routes>
        <Route path="/" element={withBoundary('Command Center', <CommandCenter />)} />
        <Route path="/division/customer-experience" element={withBoundary('Customer Experience Division', <CustomerExperienceDivision />)} />
        <Route path="/division/marketing" element={withBoundary('Marketing Division', <MarketingDivision />)} />
        <Route path="/division/product-engineering" element={withBoundary('Product / Engineering Division', <ProductEngineeringDivision />)} />
        <Route path="/division/operations" element={withBoundary('Operations Division', <OperationsDivision />)} />
        <Route path="/division/production-manufacturing" element={withBoundary('Production / Manufacturing Division', <ProductionManufacturingDivision />)} />
        <Route path="/division/product-enginering" element={<Navigate to="/division/product-engineering" replace />} />
        <Route path="/departments" element={withBoundary('Division Index', <DepartmentViews />)} />
        <Route path="/revenue" element={withBoundary('Revenue Engine', <RevenueEngine />)} />
        <Route path="/friction" element={withBoundary('Friction Map', <FrictionMap />)} />
        <Route path="/issues" element={withBoundary('Issue Radar', <IssueRadar />)} />
        <Route path="/social" element={withBoundary('Social Intelligence', <SocialIntelligence />)} />
        <Route path="/deci" element={withBoundary('DECI', <Deci />)} />
        <Route path="/lore" element={withBoundary('Lore Ledger', <LoreLedger />)} />
        <Route path="/root-cause" element={withBoundary('Root Cause', <RootCause />)} />
        <Route path="/system-health" element={withBoundary('System Health', <SystemHealthPage />)} />
        <Route path="/commercial" element={withBoundary('Revenue Engine', <RevenueEngine />)} />
        <Route path="/support" element={withBoundary('Friction Map', <FrictionMap />)} />
        <Route path="/ux" element={withBoundary('Friction Map', <FrictionMap />)} />
        <Route path="/diagnostics" element={withBoundary('Root Cause', <RootCause />)} />
        <Route path="/source-health" element={withBoundary('System Health', <SystemHealthPage />)} />
        <Route path="/analysis/cook-failures" element={withBoundary('Cook Failures Analysis', <TelemetryAnalysisPage />)} />
        <Route path="/analysis/temp-curves" element={withBoundary('Temperature Curves Analysis', <TelemetryAnalysisPage />)} />
        <Route path="/analysis/session-clusters" element={withBoundary('Session Cluster Analysis', <TelemetryAnalysisPage />)} />
        <Route path="/analysis/rssi-impact" element={withBoundary('RSSI Impact Analysis', <TelemetryAnalysisPage />)} />
        <Route path="/analysis/probe-health" element={withBoundary('Probe Health Analysis', <TelemetryAnalysisPage />)} />
        <Route path="/analysis/firmware-model" element={withBoundary('Firmware Model Analysis', <TelemetryAnalysisPage />)} />
        </Routes>
      </Layout>
    </AuthGate>
  )
}
