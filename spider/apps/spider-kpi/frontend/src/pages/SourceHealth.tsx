import { useEffect, useMemo, useRef, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { ACTIVE_CONNECTORS, isLiveConnector, isScaffolded, isTruthfullyHealthy } from '../lib/sourceHealth'
import { ActionObject, BlockedStateOutput, KPIObject, SourceHealthItem, TelemetrySummary } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract } from '../lib/divisionContract'

function statusTone(status: string) {
  switch (status) {
    case 'healthy':
      return 'good'
    case 'failed':
      return 'bad'
    case 'stale':
      return 'warn'
    case 'disabled':
      return 'muted'
    case 'not_configured':
      return 'warn'
    default:
      return 'neutral'
  }
}

function SourceCard({ row }: { row: SourceHealthItem }) {
  const scaffolded = isScaffolded(row)
  const liveConnector = isLiveConnector(row)
  const internalCompute = row.source_type === 'compute'
  const truthfulHealthy = liveConnector && isTruthfullyHealthy(row)
  const displayStatus = truthfulHealthy ? 'healthy' : row.derived_status
  const label = scaffolded ? 'scaffolded' : internalCompute ? 'compute' : 'live'
  const summary = scaffolded
    ? 'Intentionally disabled until live ingestion is implemented.'
    : truthfulHealthy
      ? 'Recent successful sync exists.'
      : row.status_summary
  const details = row.details_json || {}
  const rows15 = typeof details.rows_inserted_last_15m === 'number' ? details.rows_inserted_last_15m : null
  const rows60 = typeof details.rows_inserted_last_60m === 'number' ? details.rows_inserted_last_60m : null
  const rows24h = typeof details.rows_inserted_last_24h === 'number' ? details.rows_inserted_last_24h : null

  return (
    <div className={`list-item status-${statusTone(displayStatus)}`}>
      <div className="item-head">
        <strong>{row.source}</strong>
        <div className="inline-badges">
          <span className={`badge ${scaffolded ? 'badge-muted' : internalCompute ? 'badge-neutral' : 'badge-good'}`}>{label}</span>
          <span className={`badge badge-${statusTone(displayStatus)}`}>{displayStatus}</span>
        </div>
      </div>
      <p>{summary}</p>
      <small>
        Latest run: {row.latest_run_status} · Records: {row.latest_records_processed}
        {row.stale_minutes !== undefined && row.stale_minutes !== null ? ` · Freshness lag: ${row.stale_minutes} min` : ''}
      </small>
      {row.last_success_at ? <small>Last success: {row.last_success_at}</small> : null}
      {!truthfulHealthy ? <small>Health: {displayStatus}</small> : null}
      {row.source === 'aws_telemetry_stream' ? (
        <>
          <small><strong>lambda processing:</strong> {String(details.lambda_processing_health || 'unknown')} · <strong>ingest endpoint:</strong> {String(details.ingest_endpoint_health || 'unknown')}</small>
          <small><strong>landed-row growth:</strong> 15m {rows15 ?? 'n/a'} · 60m {rows60 ?? 'n/a'} · 24h {rows24h ?? 'n/a'}</small>
          <small><strong>latest stream sample:</strong> {String(details.latest_sample_timestamp || 'n/a')} · <strong>row age:</strong> {String(details.latest_stream_row_age_minutes ?? 'n/a')} min</small>
        </>
      ) : null}
      {row.last_error && !truthfulHealthy ? <small><strong>Last error:</strong> {row.last_error}</small> : null}
    </div>
  )
}

function formatTelemetryFreshness(timestamp?: string | null) {
  if (!timestamp) return 'n/a'
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return 'n/a'
  const ageMinutes = Math.max(0, Math.round((Date.now() - parsed) / 60000))
  if (ageMinutes < 60) return `${ageMinutes}m ago`
  const hours = Math.floor(ageMinutes / 60)
  const minutes = ageMinutes % 60
  return minutes ? `${hours}h ${minutes}m ago` : `${hours}h ago`
}

export function SourceHealthPage() {
  const [rows, setRows] = useState<SourceHealthItem[]>([])
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)

  async function load(signal?: AbortSignal) {
    const requestId = ++requestIdRef.current
    setLoading(true)
    setError(null)
    try {
      const [payload, telemetryPayload] = await Promise.all([api.sourceHealth(signal), api.telemetrySummary(signal)])
      if (signal?.aborted || requestId !== requestIdRef.current) return
      setRows(payload)
      setTelemetry(telemetryPayload)
    } catch (err) {
      if (signal?.aborted || requestId !== requestIdRef.current) return
      if (!signal?.aborted) setError(err instanceof ApiError ? err.message : 'Failed to load source health')
    } finally {
      if (signal?.aborted || requestId !== requestIdRef.current) return
      if (!signal?.aborted) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => {
      controller.abort()
      requestIdRef.current += 1
    }
  }, [])

  const liveConnectors = useMemo(() => rows.filter((row) => isLiveConnector(row)), [rows])
  const scaffoldedRows = useMemo(() => rows.filter((row) => isScaffolded(row)), [rows])
  const computeRows = useMemo(() => rows.filter((row) => row.source_type === 'compute'), [rows])
  const healthyLiveCount = useMemo(() => liveConnectors.filter((row) => isTruthfullyHealthy(row)).length, [liveConnectors])
  const staleOrFailedCount = useMemo(() => liveConnectors.filter((row) => !isTruthfullyHealthy(row)).length, [liveConnectors])
  const telemetryRows = useMemo(() => rows.filter((row) => ['aws', 'aws_telemetry', 'aws_telemetry_stream', 'venom', 'telemetry'].includes(row.source)), [rows])
  const telemetryLatest = telemetry?.latest || null
  const telemetryFallbackActive = Boolean(telemetry?.collection_metadata?.sample_source && telemetry?.collection_metadata?.sample_source !== 'dynamodb_stream')
  const snapshotTimestamp = new Date().toISOString()
  const kpis: KPIObject[] = [
    buildNumericKpi({ key: 'system_health_trusted_live_inputs', currentValue: healthyLiveCount, targetValue: liveConnectors.length || null, priorValue: null, owner: 'Joseph', truthState: 'canonical', lastUpdated: snapshotTimestamp }),
    buildNumericKpi({ key: 'system_health_decision_risk', currentValue: staleOrFailedCount, targetValue: 0, priorValue: null, owner: 'Joseph', truthState: staleOrFailedCount > 0 ? 'degraded' : 'canonical', lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'system_health_aws_venom', currentValue: telemetryRows.length ? telemetryRows.map((row) => `${row.source}:${row.derived_status}`).join(', ') : 'Not exposed', targetValue: 'Healthy', owner: 'Joseph', status: telemetryRows.some((row) => row.derived_status === 'healthy') ? 'green' : telemetryRows.length ? 'yellow' : 'red', truthState: telemetryRows.some((row) => row.derived_status === 'healthy') ? 'canonical' : telemetryRows.length ? 'degraded' : 'blocked', lastUpdated: snapshotTimestamp }),
  ]
  const blockedStates: Record<string, BlockedStateOutput> = {
    system_health_aws_venom: buildBlockedState({
      decision_blocked: 'Whether telemetry-linked product reliability decisions are complete',
      missing_source: telemetryRows.length ? 'healthy AWS/Venom telemetry' : 'AWS/Venom telemetry source row',
      still_trustworthy: ['other live connectors', 'explicit source health rows'],
      owner: 'Joseph',
      required_action_to_unblock: 'Expose and stabilize AWS/Venom telemetry source health before relying on telemetry-driven product decisions',
    }),
  }
  const actions: ActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'system-health-restore-connectors',
      triggerKpi: kpis[1],
      triggerCondition: 'decision risk count > 0',
      owner: 'Joseph',
      requiredAction: 'Restore degraded connectors before trusting affected decision surfaces.',
      priority: staleOrFailedCount > 0 ? 'critical' : 'medium',
      evidence: liveConnectors.filter((row) => !isTruthfullyHealthy(row)).map((row) => row.source),
      dueDate: '4h',
      snapshotTimestamp,
      baseRankingScore: 100,
    }),
    actionFromKpi({
      id: 'system-health-unblock-telemetry',
      triggerKpi: kpis[2],
      triggerCondition: `truth_state = ${kpis[2].truth_state}`,
      owner: 'Joseph',
      requiredAction: 'Unblock AWS/Venom telemetry source health before treating telemetry-linked insights as complete.',
      priority: 'high',
      evidence: telemetryRows.map((row) => row.source),
      dueDate: 'next integration pass',
      snapshotTimestamp,
      baseRankingScore: 80,
      blockedState: blockedStates.system_health_aws_venom,
    }),
  ])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>System Health</h2>
        <p>Data trust, connector health, and execution reliability for the decision system.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {!loading && !error ? (
        <div className="three-col">
          <Card title="Trusted Live Inputs"><div className="hero-metric">{healthyLiveCount}/{liveConnectors.length || 0}</div><div className="state-message">Decision-grade live integrations</div></Card>
          <Card title="Decision Risk"><div className="hero-metric">{staleOrFailedCount}</div><div className="state-message">Connectors currently reducing decision confidence</div></Card>
          <Card title="Scaffolded / Compute"><div className="hero-metric">{scaffoldedRows.length + computeRows.length}</div><div className="state-message">Non-live sources separated from real connector health</div></Card>
        </div>
      ) : null}
      {loading ? <Card title="Source Health Status"><div className="state-message">Loading live source health…</div></Card> : null}
      {error ? <Card title="Source Health Error"><div className="state-message error">{error}</div><button className="button" onClick={() => void load()}>Retry</button></Card> : null}
      {!loading && !error ? (
        <>
          <Card title="AWS / Venom Telemetry Health">
            <div className="stack-list">
              {telemetryFallbackActive ? <div className="list-item status-bad"><div className="item-head"><strong>production fallback warning</strong><span className="badge badge-bad">bounded-scan active</span></div><p>Telemetry summary is no longer stream-backed. Production is currently serving telemetry from a bounded scan path again.</p><small><strong>sample source:</strong> {telemetry?.collection_metadata?.sample_source || 'unknown'} · <strong>source:</strong> {telemetry?.collection_metadata?.source || 'unknown'}</small><small><strong>reason:</strong> {telemetry?.confidence?.reason || telemetry?.collection_metadata?.coverage_summary || 'No fallback reason returned.'}</small></div> : null}
              {telemetryRows.map((row) => <SourceCard key={row.source} row={row} />)}
              {telemetryLatest ? <div className={`list-item status-${(telemetryLatest.session_reliability_score || 0) >= 0.8 ? 'good' : (telemetryLatest.session_reliability_score || 0) >= 0.6 ? 'warn' : 'bad'}`}><div className="item-head"><strong>telemetry latest aggregate</strong><span className="badge badge-neutral">{telemetryLatest.business_date}</span></div><p>Active devices 5m/15m/60m: {telemetry?.collection_metadata?.active_devices_last_5m ?? 'n/a'} / {telemetry?.collection_metadata?.active_devices_last_15m ?? 'n/a'} / {telemetry?.collection_metadata?.active_devices_last_60m ?? 'n/a'} · latest sample {formatTelemetryFreshness(telemetry?.collection_metadata?.newest_sample_timestamp_seen)}</p><small><strong>mode:</strong> {telemetry?.collection_metadata?.sample_source === 'dynamodb_stream' ? 'stream-backed' : `fallback:${telemetry?.collection_metadata?.sample_source || 'unknown'}`}</small><small><strong>observed reliability:</strong> {(telemetryLatest.session_reliability_score * 100).toFixed(0)}% · <strong>disconnect proxy:</strong> {(telemetryLatest.disconnect_rate * 100).toFixed(1)}% · <strong>error proxy:</strong> {(telemetryLatest.error_rate * 100).toFixed(1)}%</small><small><strong>firmware health:</strong> {(telemetryLatest.firmware_health_score * 100).toFixed(0)}% · <strong>temp stability:</strong> {(telemetryLatest.temp_stability_score * 100).toFixed(0)}% · <strong>manual override:</strong> {(telemetryLatest.manual_override_rate * 100).toFixed(1)}%</small><small><strong>confidence:</strong> {telemetry?.confidence?.global_completeness || 'unknown'} global completeness · {telemetry?.confidence?.session_derivation || 'unknown'} session derivation</small><small><strong>coverage summary:</strong> {telemetry?.collection_metadata?.coverage_summary || telemetry?.confidence?.reason || 'No telemetry coverage summary returned.'}</small><small><strong>coverage quality:</strong> distinct devices {telemetry?.collection_metadata?.distinct_devices_observed ?? 'n/a'} · engaged devices {telemetry?.collection_metadata?.distinct_engaged_devices_observed ?? telemetry?.collection_metadata?.engaged_latest_devices ?? 'n/a'} · oldest {telemetry?.collection_metadata?.oldest_sample_timestamp_seen ?? 'n/a'} · newest {telemetry?.collection_metadata?.newest_sample_timestamp_seen ?? 'n/a'}</small><small><strong>bounds:</strong> max cap hit {String(telemetry?.collection_metadata?.max_record_cap_hit ?? false)} · gap timeout {telemetry?.collection_metadata?.session_gap_timeout_minutes ?? 'n/a'} min · pages {telemetry?.collection_metadata?.pages_scanned ?? 'n/a'}{telemetry?.collection_metadata?.scan_truncated ? ' (truncated)' : ''}</small></div> : null}
              {!telemetryRows.length ? <div className="list-item status-bad"><p>{blockedStates.system_health_aws_venom.decision_blocked}</p><small><strong>truth_state:</strong> {kpis[2].truth_state} · <strong>missing source:</strong> {blockedStates.system_health_aws_venom.missing_source}</small><small><strong>owner:</strong> {blockedStates.system_health_aws_venom.owner} · <strong>next action:</strong> {actions[1]?.required_action}</small></div> : null}
            </div>
          </Card>
          <Card title="Live Connectors">
            <div className="stack-list">
              {liveConnectors.map((row) => <SourceCard key={row.source} row={row} />)}
              {!liveConnectors.length ? <div className="state-message">No live connector rows returned.</div> : null}
            </div>
          </Card>
          <div className="two-col">
            <Card title="Scaffolded Sources">
              <div className="stack-list">
                {scaffoldedRows.map((row) => <SourceCard key={row.source} row={row} />)}
                {!scaffoldedRows.length ? <div className="state-message">No scaffolded rows returned.</div> : null}
              </div>
            </Card>
            <Card title="Internal Compute">
              <div className="stack-list">
                {computeRows.map((row) => <SourceCard key={row.source} row={row} />)}
                {!computeRows.length ? <div className="state-message">No compute rows returned.</div> : null}
              </div>
            </Card>
          </div>
          <Card title="Raw Source Health Table">
            {rows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Type</th>
                      <th>Configured</th>
                      <th>Enabled</th>
                      <th>Run Status</th>
                      <th>Derived</th>
                      <th>Blocks Connector Health</th>
                      <th>Last Success</th>
                      <th>Records</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.source}>
                        <td>{row.source}</td>
                        <td>{row.source_type || 'connector'}</td>
                        <td>{String(row.configured)}</td>
                        <td>{String(row.enabled)}</td>
                        <td>{row.latest_run_status}</td>
                        <td>{isLiveConnector(row) && isTruthfullyHealthy(row) ? 'healthy' : row.derived_status}</td>
                        <td>{String(row.blocks_connector_health ?? true)}</td>
                        <td>{row.last_success_at || '—'}</td>
                        <td>{row.latest_records_processed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="state-message">No source health rows returned.</div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  )
}
