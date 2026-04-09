import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Card } from '../components/Card'
import { ApiError, api } from '../lib/api'
import { TelemetrySummary } from '../lib/types'

const PAGE_META: Record<string, { title: string, subtitle: string }> = {
  '/analysis/cook-failures': {
    title: 'Cook Failure Analysis',
    subtitle: 'Drop-off reasons, lifecycle transitions, and observed failure concentration from stream-derived sessions.',
  },
  '/analysis/temp-curves': {
    title: 'Temperature Curves Analysis',
    subtitle: 'Pit vs target curve buckets, stabilization timing, and control-quality heuristics.',
  },
  '/analysis/session-clusters': {
    title: 'Session Cluster Analysis',
    subtitle: 'Observed session archetypes, clustering heuristics, and representative pattern mix.',
  },
  '/analysis/rssi-impact': {
    title: 'RSSI Impact Analysis',
    subtitle: 'Connectivity cohorts, stability correlation, and disconnect-proxy concentration by RSSI bucket.',
  },
  '/analysis/probe-health': {
    title: 'Probe Health Analysis',
    subtitle: 'Probe usage coverage and blocked-state handling when probe telemetry is thin or unavailable.',
  },
  '/analysis/firmware-model': {
    title: 'Firmware / Model Cohort Analysis',
    subtitle: 'Cohort comparison with explicit n, uncertainty, and observed degradation patterns.',
  },
}

export function TelemetryAnalysisPage() {
  const location = useLocation()
  const meta = PAGE_META[location.pathname] || { title: 'Telemetry Analysis', subtitle: 'Observed telemetry analysis page.' }
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.telemetrySummary()
        if (!cancelled) setTelemetry(payload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load telemetry analysis')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const streamBacked = telemetry?.collection_metadata?.sample_source === 'dynamodb_stream'
  const sampleSize = telemetry?.slice_snapshot?.sessions_derived || telemetry?.collection_metadata?.distinct_devices_observed || 0
  const sampleReliability = !streamBacked ? 'low' : sampleSize < 5 ? 'low' : sampleSize < 20 ? 'medium' : 'high'
  const blocksProbe = location.pathname === '/analysis/probe-health' && !(telemetry?.analytics?.probe_usage || []).some((row) => row.probe_count > 0)

  const rows = useMemo(() => {
    switch (location.pathname) {
      case '/analysis/cook-failures':
        return telemetry?.analytics?.dropoff_reasons?.map((row) => ({ label: row.reason, value: `${row.sessions} sessions · ${(row.rate * 100).toFixed(0)}%` })) || []
      case '/analysis/temp-curves':
        return telemetry?.analytics?.pit_temperature_curve?.slice(0, 15).map((row) => ({ label: `min ${row.minute_bucket}`, value: `p50 ${row.p50_temp_delta ?? '—'}° · p90 ${row.p90_temp_delta ?? '—'}° · n=${row.sessions}` })) || []
      case '/analysis/session-clusters':
        return telemetry?.analytics?.session_archetypes?.map((row) => ({ label: row.archetype, value: `${(row.rate * 100).toFixed(0)}% · ${row.description}` })) || []
      case '/analysis/rssi-impact':
        return telemetry?.analytics?.connectivity_buckets?.map((row) => ({ label: row.bucket, value: `n=${row.sessions} · fail ${(row.failure_rate * 100).toFixed(0)}% · stability ${row.stability_score !== null && row.stability_score !== undefined ? (row.stability_score * 100).toFixed(0) : '—'}%` })) || []
      case '/analysis/probe-health':
        return telemetry?.analytics?.probe_usage?.map((row) => ({ label: `${row.probe_count} probes`, value: `n=${row.sessions} · ${(row.rate * 100).toFixed(0)}%` })) || []
      case '/analysis/firmware-model':
        return [
          ...(telemetry?.firmware_health || []).slice(0, 6).map((row) => ({ label: `Firmware ${row.key}`, value: `n=${row.sessions} · fail ${(row.failure_rate * 100).toFixed(0)}% · disconnect ${(row.disconnect_rate * 100).toFixed(0)}%` })),
          ...(telemetry?.grill_type_health || []).slice(0, 6).map((row) => ({ label: `Model ${row.key}`, value: `n=${row.sessions} · fail ${(row.failure_rate * 100).toFixed(0)}% · disconnect ${(row.disconnect_rate * 100).toFixed(0)}%` })),
        ]
      default:
        return []
    }
  }, [location.pathname, telemetry])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>{meta.title}</h2>
        <p>{meta.subtitle}</p>
      </div>
      <Card title="Analysis status">
        {loading ? <div className="state-message">Loading analysis…</div> : null}
        {error ? <div className="state-message error">{error}</div> : null}
        {!loading && !error ? (
          <div className="stack-list compact">
            <div className="list-item status-neutral"><strong>truth_state</strong><p>{streamBacked ? 'estimated / proxy depending on metric' : 'blocked or low-confidence fallback'}</p><small>sample size {sampleSize} · sample reliability {sampleReliability}</small></div>
            {blocksProbe ? <div className="list-item status-bad"><strong>Probe analysis blocked</strong><p>Raw stream payload in the current slice does not expose enough probe telemetry to support reliable probe-health analytics.</p><small>Owner: Kyle · Still trustworthy: cook lifecycle, control quality, connectivity, cohort mix.</small></div> : null}
            {rows.map((row) => <div className="list-item status-muted" key={row.label}><strong>{row.label}</strong><p>{row.value}</p></div>)}
            {!rows.length ? <div className="state-message">No deeper analysis rows available for this section yet.</div> : null}
          </div>
        ) : null}
      </Card>
      <Card title="Back to Product / Engineering">
        <Link to="/division/product-engineering">Return to Product / Engineering</Link>
      </Card>
    </div>
  )
}
