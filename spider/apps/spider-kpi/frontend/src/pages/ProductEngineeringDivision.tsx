import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { DecisionStack } from '../components/DecisionStack'
import { ApiError, api, getApiBase } from '../lib/api'
import { BlockedStateOutput, KPIObject, TelemetrySummary } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, RankedActionObject } from '../lib/divisionContract'

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

function pct(value?: number | null, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function secondsToMinutes(value?: number | null, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value / 60).toFixed(digits)} min`
}

function metricTruthState(streamBacked: boolean, hasAnalytics: boolean): KPIObject['truth_state'] {
  if (!streamBacked) return 'blocked'
  return hasAnalytics ? 'estimated' : 'proxy'
}

export function ProductEngineeringDivision() {
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
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load telemetry summary')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const snapshotTimestamp = new Date().toISOString()
  const latest = telemetry?.latest || null
  const slice = telemetry?.slice_snapshot || null
  const collection = telemetry?.collection_metadata || null
  const analytics = telemetry?.analytics || null
  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const hasAnalytics = Boolean(analytics?.cook_lifecycle_funnel?.length)
  const analyticsTruthState = metricTruthState(streamBacked, hasAnalytics)
  const coverageTruthState: KPIObject['truth_state'] = streamBacked ? 'proxy' : 'blocked'
  const sampleSize = Math.max(collection?.distinct_devices_observed || 0, slice?.sessions_derived || 0, collection?.active_devices_last_15m || 0)
  const sampleScope = streamBacked
    ? `${collection?.distinct_devices_observed || 0} devices, ${slice?.sessions_derived || 0} derived sessions, ${collection?.records_loaded || 0} stream rows`
    : `${collection?.distinct_devices_observed || 0} device(s) from bounded fallback telemetry`
  const sampleReliability: KPIObject['sample_reliability'] = !streamBacked ? 'low' : sampleSize < 5 ? 'low' : sampleSize < 20 ? 'medium' : 'high'
  const limitedSampleNote = sampleReliability === 'low' ? 'Limited sample — directional only.' : null

  const derived = analytics?.derived_metrics
  const funnel = analytics?.cook_lifecycle_funnel || []
  const dropoffs = analytics?.dropoff_reasons || []
  const connectivity = analytics?.connectivity_buckets || []
  const issueInsights = analytics?.issue_insights || []
  const archetypes = analytics?.session_archetypes || []
  const probeUsage = analytics?.probe_usage || []
  const curve = analytics?.pit_temperature_curve || []
  const worstFirmware = telemetry?.firmware_health?.[0] || null
  const worstModel = telemetry?.grill_type_health?.[0] || null
  const worstConnectivity = [...connectivity].sort((a, b) => b.failure_rate - a.failure_rate)[0] || null

  const kpis: KPIObject[] = useMemo(() => [
    buildNumericKpi({ key: 'product_session_success_rate', currentValue: derived?.session_success_rate ?? latest?.cook_success_rate ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, thresholds: { greenAtOrAbove: 0.85, yellowAtOrAbove: 0.7 }, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_stability_score', currentValue: derived?.stability_score ?? latest?.temp_stability_score ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, thresholds: { greenAtOrAbove: 0.8, yellowAtOrAbove: 0.65 }, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_overshoot_rate', currentValue: derived?.overshoot_rate ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, thresholds: { greenAtOrAbove: 0, yellowAtOrAbove: 0 }, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_disconnect_proxy_rate', currentValue: derived?.disconnect_proxy_rate ?? latest?.disconnect_rate ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, thresholds: { greenAtOrAbove: 0, yellowAtOrAbove: 0 }, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_time_to_stabilize_seconds', currentValue: derived?.time_to_stabilize_seconds ?? latest?.avg_time_to_stabilization_seconds ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildTextKpi({ key: 'product_probe_coverage', currentValue: analytics ? `${probeUsage.map((row) => `${row.probe_count} probes: ${pct(row.rate)}`).join(' · ') || 'No probe telemetry observed'}${limitedSampleNote ? ` ${limitedSampleNote}` : ''}` : null, targetValue: 'Consistent observable probe usage', owner: 'Kyle', status: analytics?.probe_failure_rate && analytics.probe_failure_rate > 0.2 ? 'yellow' : 'green', truthState: streamBacked ? 'estimated' : 'blocked', lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildTextKpi({ key: 'product_coverage_quality', currentValue: collection?.coverage_summary || 'No telemetry coverage summary', targetValue: 'Broad trustworthy observed slice', owner: 'Joseph', status: streamBacked ? 'yellow' : 'red', truthState: coverageTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
  ], [derived, latest, analyticsTruthState, snapshotTimestamp, sampleSize, sampleScope, sampleReliability, analytics, probeUsage, limitedSampleNote, collection, streamBacked, coverageTruthState])

  const blockedStates: Record<string, BlockedStateOutput> = {
    product_coverage_quality: buildBlockedState({
      decision_blocked: 'Whether Product / Engineering telemetry can be generalized to full-fleet product truth',
      missing_source: streamBacked ? 'canonical cook-session ledger / account-linked cook truth' : 'live stream-backed telemetry analytics path',
      still_trustworthy: ['recent device activity windows', 'observed slice cohort comparisons', 'stream-derived funnel and RSSI proxies when stream-backed'],
      owner: 'Joseph',
      required_action_to_unblock: streamBacked ? 'Keep claims scoped to observed device-session heuristics until historical backfill and canonical cook semantics are added.' : 'Restore stream-backed telemetry and do not generalize fallback telemetry into fleet-wide product claims.',
    }),
  }

  const actions: RankedActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'product-review-funnel-dropoff',
      triggerKpi: kpis[0],
      triggerCondition: 'session success or completion funnel is weak',
      owner: 'Kyle',
      requiredAction: `Inspect derived sessions that fail between started -> reached_target -> stable -> completed; prioritize top drop-off reason (${dropoffs[0]?.reason || 'n/a'}) before broad product claims.`,
      priority: (derived?.session_success_rate || 0) < 0.6 ? 'critical' : 'high',
      evidence: [`session_success=${pct(derived?.session_success_rate)}`, `top_dropoff=${dropoffs[0]?.reason || 'n/a'}`, `funnel_started=${funnel[0]?.sessions || 0}`, `funnel_completed=${funnel[3]?.sessions || 0}`],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Math.round((1 - (derived?.session_success_rate || 0)) * 100) + 30,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'product-review-connectivity-cohort',
      triggerKpi: kpis[3],
      triggerCondition: 'disconnect proxy or weak-RSSI cohort underperforms',
      owner: 'Kyle',
      requiredAction: `Compare session stability and failure by RSSI bucket, starting with ${worstConnectivity?.bucket || 'weakest observed bucket'}, then isolate firmware/model concentration inside that bucket before escalating to hardware or controls work.`,
      priority: (derived?.disconnect_proxy_rate || 0) >= 0.25 ? 'critical' : 'high',
      evidence: [`disconnect_proxy=${pct(derived?.disconnect_proxy_rate)}`, `worst_rssi_bucket=${worstConnectivity?.bucket || 'n/a'}`, `bucket_failure=${pct(worstConnectivity?.failure_rate)}`],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Math.round((derived?.disconnect_proxy_rate || 0) * 100) + Math.round((worstConnectivity?.failure_rate || 0) * 100),
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'product-review-worst-cohort',
      triggerKpi: kpis[1],
      triggerCondition: 'firmware/model cohort materially underperforms in observed sessions',
      owner: 'Kyle',
      requiredAction: `Review the worst observed firmware/model cohorts (firmware ${worstFirmware?.key || 'n/a'}, model ${worstModel?.key || 'n/a'}) and compare stability, failure, and disconnect proxies before assigning root cause.`,
      priority: (worstFirmware?.failure_rate || 0) >= 0.25 || (worstModel?.failure_rate || 0) >= 0.25 ? 'high' : 'medium',
      evidence: [`worst_firmware=${worstFirmware?.key || 'n/a'}:${pct(worstFirmware?.failure_rate)}`, `worst_model=${worstModel?.key || 'n/a'}:${pct(worstModel?.failure_rate)}`],
      dueDate: '48h',
      snapshotTimestamp,
      baseRankingScore: Math.round(((worstFirmware?.failure_rate || 0) + (worstModel?.failure_rate || 0)) * 50) + 20,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'product-coverage-warning',
      triggerKpi: kpis[6],
      triggerCondition: 'page is still using proxy telemetry rather than canonical cook truth',
      owner: 'Joseph',
      requiredAction: 'Keep product conclusions scoped to observed stream-derived telemetry until historical backfill and stronger canonical cook semantics are added.',
      priority: 'critical',
      evidence: [collection?.coverage_summary || 'telemetry coverage summary', telemetry?.confidence?.reason || 'proxy telemetry path'],
      dueDate: 'now',
      snapshotTimestamp,
      baseRankingScore: 95,
      blockedState: blockedStates.product_coverage_quality,
      scope: 'observed_slice',
      confidence: 'low',
    }),
  ]).slice(0, 5)

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Product / Engineering</h2>
        <p>Stream-backed telemetry analytics for cook behavior, failure modes, cohort risk, and connectivity. No ingestion changes; truth-state preserved.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Product / Engineering"><div className="state-message">Loading telemetry analytics…</div></Card> : null}
      {error ? <Card title="Product / Engineering Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Session success"><div className="hero-metric">{pct(derived?.session_success_rate ?? latest?.cook_success_rate)}</div><div className="state-message">truth_state: {kpis[0].truth_state} · sample {sampleReliability}</div></Card>
            <Card title="Stability score"><div className="hero-metric">{pct(derived?.stability_score ?? latest?.temp_stability_score)}</div><div className="state-message">derived from stream session heuristics · sample {sampleScope}</div></Card>
            <Card title="Disconnect proxy"><div className="hero-metric">{pct(derived?.disconnect_proxy_rate ?? latest?.disconnect_rate)}</div><div className="state-message">gap/RSSI proxy, not canonical disconnect event truth</div></Card>
          </div>
          <DecisionStack actions={actions} />

          <div className="two-col">
            <Card title="Cook lifecycle funnel">
              <div className="stack-list compact">
                {funnel.map((step) => (
                  <div className={`list-item status-${step.rate >= 0.8 ? 'good' : step.rate >= 0.5 ? 'warn' : 'bad'}`} key={step.step}>
                    <div className="item-head"><strong>{step.step.replace('_', ' ')}</strong><span>{step.sessions} sessions</span></div>
                    <p>{pct(step.rate)} of started sessions reached this stage.</p>
                    <small>Rendered from stream-derived session lifecycle heuristics · truth_state: {kpis[0].truth_state}</small>
                  </div>
                ))}
                {!funnel.length ? <div className="state-message">No stream-backed funnel rows returned.</div> : null}
              </div>
            </Card>
            <Card title="Drop-off reasons">
              <div className="stack-list compact">
                {dropoffs.map((row) => (
                  <div className="list-item status-warn" key={row.reason}>
                    <div className="item-head"><strong>{row.reason.replace(/_/g, ' ')}</strong><span>{pct(row.rate)}</span></div>
                    <p>{row.sessions} derived sessions dropped here.</p>
                  </div>
                ))}
                {!dropoffs.length ? <div className="state-message">No material drop-off reason was returned from the current observed slice.</div> : null}
              </div>
            </Card>
          </div>

          <div className="two-col">
            <Card title="Time vs temperature analytics">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Minute</th><th>P50 pit-target Δ</th><th>P90 pit-target Δ</th><th>Samples</th></tr>
                  </thead>
                  <tbody>
                    {curve.map((row) => (
                      <tr key={row.minute_bucket}>
                        <td>{row.minute_bucket}</td>
                        <td>{row.p50_temp_delta ?? '—'}°</td>
                        <td>{row.p90_temp_delta ?? '—'}°</td>
                        <td>{row.sessions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="state-message">Aggregate pit vs target deltas from derived stream sessions. Truth state: {kpis[1].truth_state}.</div>
            </Card>
            <Card title="Session archetypes">
              <div className="stack-list compact">
                {archetypes.map((row) => (
                  <div className={`list-item status-${row.archetype === 'stable' ? 'good' : row.archetype === 'dropout' ? 'bad' : 'warn'}`} key={row.archetype}>
                    <div className="item-head"><strong>{row.archetype}</strong><span>{pct(row.rate)}</span></div>
                    <p>{row.description}</p>
                    <small>{row.sessions} sessions in observed slice.</small>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <div className="two-col">
            <Card title="Probe analytics">
              <div className="stack-list compact">
                <div className="list-item status-neutral"><strong>probe usage rate</strong><p>{probeUsage.map((row) => `${row.probe_count}: ${pct(row.rate)}`).join(' · ') || 'No probe telemetry observed in current slice.'}</p></div>
                <div className="list-item status-warn"><strong>probe failure rate</strong><p>{pct(analytics?.probe_failure_rate)}</p><small>Only computed when raw payload exposes probe-like fields; otherwise remains unavailable.</small></div>
                <div className="list-item status-neutral"><strong>pit vs probe delta</strong><p>{analytics?.pit_probe_delta_avg !== null && analytics?.pit_probe_delta_avg !== undefined ? `${analytics.pit_probe_delta_avg}° avg absolute delta` : 'Unavailable from current payload shape.'}</p></div>
              </div>
            </Card>
            <Card title="Connectivity analysis">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>RSSI bucket</th><th>Sessions</th><th>Failure rate</th><th>Stability score</th></tr>
                  </thead>
                  <tbody>
                    {connectivity.map((row) => (
                      <tr key={row.bucket}>
                        <td>{row.bucket}</td>
                        <td>{row.sessions}</td>
                        <td>{pct(row.failure_rate)}</td>
                        <td>{pct(row.stability_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <div className="two-col">
            <Card title="Cohort comparison · firmware">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Firmware</th><th>Sessions</th><th>Failure</th><th>Disconnect</th><th>Health</th></tr>
                  </thead>
                  <tbody>
                    {(telemetry?.firmware_health || []).slice(0, 8).map((row) => (
                      <tr key={row.key}>
                        <td>{row.key}</td>
                        <td>{row.sessions}</td>
                        <td>{pct(row.failure_rate)}</td>
                        <td>{pct(row.disconnect_rate)}</td>
                        <td>{pct(row.health_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Cohort comparison · model">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Model</th><th>Sessions</th><th>Failure</th><th>Disconnect</th><th>Health</th></tr>
                  </thead>
                  <tbody>
                    {(telemetry?.grill_type_health || []).slice(0, 8).map((row) => (
                      <tr key={row.key}>
                        <td>{row.key}</td>
                        <td>{row.sessions}</td>
                        <td>{pct(row.failure_rate)}</td>
                        <td>{pct(row.disconnect_rate)}</td>
                        <td>{pct(row.health_score)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <div className="three-col">
            <Card title="Derived metric · overshoot rate"><div className="hero-metric hero-metric-sm">{pct(derived?.overshoot_rate)}</div><div className="state-message">Rendered in top analytics KPI strip.</div></Card>
            <Card title="Derived metric · time to stabilize"><div className="hero-metric hero-metric-sm">{secondsToMinutes(derived?.time_to_stabilize_seconds)}</div><div className="state-message">Derived from first stable 3-hit target band in stream session heuristic.</div></Card>
            <Card title="Derived metric · active devices last 15m"><div className="hero-metric hero-metric-sm">{collection?.active_devices_last_15m ?? 0}</div><div className="state-message">Device-level recent activity proxy, not users.</div></Card>
          </div>

          <div className="two-col">
            <Card title="Structured issue detection">
              <div className="stack-list compact">
                {issueInsights.map((row, index) => (
                  <div className={`list-item status-${row.confidence === 'high' ? 'bad' : row.confidence === 'medium' ? 'warn' : 'muted'}`} key={`${row.issue}-${index}`}>
                    <strong>{row.issue}</strong>
                    <p>{row.signal}</p>
                    <small><strong>cohort:</strong> {row.cohort} · <strong>confidence:</strong> {row.confidence}</small>
                    <small><strong>action:</strong> {row.action}</small>
                  </div>
                ))}
                {!issueInsights.length ? <div className="state-message">No structured issue insight crossed threshold in the current observed slice.</div> : null}
              </div>
            </Card>
            <Card title="Telemetry health / truth handling">
              <div className="stack-list compact">
                <div className="list-item status-muted"><strong>coverage summary</strong><p>{collection?.coverage_summary || 'No telemetry coverage summary returned.'}</p><small>latest sample {formatTelemetryFreshness(collection?.newest_sample_timestamp_seen)}</small></div>
                <div className="list-item status-neutral"><strong>truth_state proof</strong><p>Cook lifecycle, stability, overshoot, disconnect proxy, and cohort analytics remain <strong>{analyticsTruthState}</strong>; coverage/generalization remains <strong>{coverageTruthState}</strong>.</p><small>This preserves the existing truth_state system and blocks fleet-general conclusions.</small></div>
                <div className="list-item status-bad"><strong>{blockedStates.product_coverage_quality.decision_blocked}</strong><p>{blockedStates.product_coverage_quality.missing_source}</p><small><strong>still trustworthy:</strong> {blockedStates.product_coverage_quality.still_trustworthy.join(', ')}</small><small><strong>next action:</strong> {blockedStates.product_coverage_quality.required_action_to_unblock}</small></div>
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
