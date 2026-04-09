import { ReactNode, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
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

function statusTone(value: number | null | undefined, goodAt: number, warnAt: number, inverse = false) {
  if (value === null || value === undefined || Number.isNaN(value)) return 'muted'
  if (inverse) {
    if (value <= goodAt) return 'good'
    if (value <= warnAt) return 'warn'
    return 'bad'
  }
  if (value >= goodAt) return 'good'
  if (value >= warnAt) return 'warn'
  return 'bad'
}

function drillLabel(path: string, label: string) {
  return <Link className="analysis-link" to={path}>{label} →</Link>
}

function MiniKpiCard({
  title,
  value,
  subtext,
  link,
  tone,
  kpi,
}: {
  title: string
  value: string
  subtext: string
  link: ReactNode
  tone: string
  kpi: KPIObject
}) {
  return (
    <Card title={title}>
      <div className={`analytics-kpi analytics-kpi-${tone}`}>
        <div className="hero-metric">{value}</div>
        <div className="inline-badges">
          <span className={`badge ${kpi.truth_state === 'blocked' ? 'badge-bad' : kpi.truth_state === 'estimated' || kpi.truth_state === 'proxy' ? 'badge-warn' : 'badge-good'}`}>{kpi.truth_state}</span>
          <span className="badge badge-neutral">n {kpi.sample_size ?? '—'}</span>
          <span className="badge badge-neutral">sample {kpi.sample_reliability || '—'}</span>
        </div>
        <p className="metric-subcopy">{subtext}</p>
        <small>{kpi.sample_scope}</small>
        <div className="metric-link-row">{link}</div>
      </div>
    </Card>
  )
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
  const derived = analytics?.derived_metrics || null
  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const sampleSize = Math.max(slice?.sessions_derived || 0, collection?.distinct_devices_observed || 0, collection?.active_devices_last_15m || 0)
  const sampleScope = streamBacked
    ? `${collection?.distinct_devices_observed || 0} devices · ${slice?.sessions_derived || 0} derived sessions · ${collection?.records_loaded || 0} stream rows · latest ${formatTelemetryFreshness(collection?.newest_sample_timestamp_seen)}`
    : `${collection?.distinct_devices_observed || 0} devices from fallback telemetry — not safe for full product claims`
  const sampleReliability: KPIObject['sample_reliability'] = !streamBacked ? 'low' : sampleSize < 5 ? 'low' : sampleSize < 20 ? 'medium' : 'high'
  const analyticsTruthState: KPIObject['truth_state'] = streamBacked ? 'estimated' : 'blocked'
  const summaryTruthState: KPIObject['truth_state'] = streamBacked ? 'proxy' : 'blocked'
  const probeAvailable = Boolean((analytics?.probe_usage || []).some((row) => row.probe_count > 0) || analytics?.pit_probe_delta_avg !== null && analytics?.pit_probe_delta_avg !== undefined)

  const activeCooksKpi = buildNumericKpi({ key: 'active_cooks_now', currentValue: derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? null, targetValue: null, owner: 'Kyle', truthState: summaryTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability })
  const throughputKpi = buildNumericKpi({ key: 'cook_throughput', currentValue: derived?.cooks_completed_24h ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability })
  const reliabilityKpi = buildNumericKpi({ key: 'session_success_rate', currentValue: derived?.session_success_rate ?? latest?.session_reliability_score ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability, thresholds: { greenAtOrAbove: 0.8, yellowAtOrAbove: 0.65 } })
  const controlKpi = buildNumericKpi({ key: 'control_quality', currentValue: derived?.stability_score ?? latest?.temp_stability_score ?? null, targetValue: null, owner: 'Kyle', truthState: analyticsTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability, thresholds: { greenAtOrAbove: 0.8, yellowAtOrAbove: 0.65 } })
  const probeBlockedKpi = buildTextKpi({ key: 'probe_health_blocked', currentValue: probeAvailable ? 'Probe telemetry available in current slice.' : 'Probe telemetry is too thin or absent in current stream slice.', targetValue: 'Probe telemetry available', owner: 'Kyle', status: probeAvailable ? 'green' : 'red', truthState: probeAvailable ? analyticsTruthState : 'blocked', lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability })

  const blockedStates: Record<string, BlockedStateOutput> = {
    probe_health: buildBlockedState({
      decision_blocked: 'Probe-health conclusions at fleet level',
      missing_source: 'consistent probe telemetry fields in the current raw stream payload',
      still_trustworthy: ['active cooks', 'cook lifecycle funnel', 'temperature control quality', 'connectivity correlation', 'firmware/model cohorts'],
      owner: 'Kyle',
      required_action_to_unblock: 'Confirm stable ingestion of probe telemetry fields across stream rows before turning probe analytics into a primary decision surface.',
    }),
    generalization: buildBlockedState({
      decision_blocked: 'Full-fleet product truth from this page',
      missing_source: streamBacked ? 'canonical cook ledger / historical backfill' : 'live stream-backed telemetry path',
      still_trustworthy: ['observed_slice product patterns', 'recent activity windows', 'cohort comparisons with explicit n', 'proxy-based issue detection'],
      owner: 'Joseph',
      required_action_to_unblock: streamBacked ? 'Keep this page scoped to observed slice telemetry until historical/canonical cook truth is added.' : 'Restore stream-backed telemetry before making product decisions from this page.',
    }),
  }

  const actions: RankedActionObject[] = useMemo(() => enforceActionContract([
    actionFromKpi({
      id: 'pe_review_failed_funnel_stage',
      triggerKpi: reliabilityKpi,
      triggerCondition: 'cook lifecycle funnel completion or success is weak',
      owner: 'Kyle',
      requiredAction: `Review the biggest funnel break (${analytics?.dropoff_reasons?.[0]?.reason || 'n/a'}) and inspect failed sessions through /analysis/cook-failures before escalating remediation.`,
      priority: (derived?.session_success_rate || 0) < 0.6 ? 'critical' : 'high',
      evidence: [`success=${pct(derived?.session_success_rate)}`, `completed_24h=${derived?.cooks_completed_24h ?? 0}`, `dropoff=${analytics?.dropoff_reasons?.[0]?.reason || 'n/a'}`],
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: Math.round((1 - (derived?.session_success_rate || 0)) * 100) + 35,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'pe_review_connectivity_risk',
      triggerKpi: controlKpi,
      triggerCondition: 'low RSSI correlates with lower stability or higher failure',
      owner: 'Kyle',
      requiredAction: 'Use /analysis/rssi-impact to compare weak-signal cohorts against stronger-signal sessions, then separate connectivity-driven instability from control-loop issues.',
      priority: ((analytics?.connectivity_buckets || []).some((row) => (row.failure_rate || 0) >= 0.35) ? 'high' : 'medium'),
      evidence: (analytics?.connectivity_buckets || []).slice(0, 2).map((row) => `${row.bucket}: fail ${pct(row.failure_rate)} · stability ${pct(row.stability_score)}`),
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: Math.round(((analytics?.connectivity_buckets || [])[0]?.failure_rate || 0) * 100) + 25,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'pe_review_worst_cohort',
      triggerKpi: throughputKpi,
      triggerCondition: 'firmware/model cohorts show concentrated degradation',
      owner: 'Kyle',
      requiredAction: 'Use /analysis/firmware-model to inspect the worst firmware/model cohort with explicit n before assigning product or firmware root cause.',
      priority: ((telemetry?.firmware_health?.[0]?.failure_rate || 0) >= 0.25 || (telemetry?.grill_type_health?.[0]?.failure_rate || 0) >= 0.25) ? 'high' : 'medium',
      evidence: [`fw=${telemetry?.firmware_health?.[0]?.key || 'n/a'} ${pct(telemetry?.firmware_health?.[0]?.failure_rate)}`, `model=${telemetry?.grill_type_health?.[0]?.key || 'n/a'} ${pct(telemetry?.grill_type_health?.[0]?.failure_rate)}`],
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: Math.round(((telemetry?.firmware_health?.[0]?.failure_rate || 0) + (telemetry?.grill_type_health?.[0]?.failure_rate || 0)) * 50) + 20,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : 'medium',
    }),
    actionFromKpi({
      id: 'pe_probe_blocked',
      triggerKpi: probeBlockedKpi,
      triggerCondition: 'probe telemetry is thin or missing',
      owner: 'Kyle',
      requiredAction: probeAvailable ? 'Probe telemetry is present; use /analysis/probe-health for deeper review.' : 'Keep probe-related conclusions investigative only and unblock by confirming stable probe-field coverage in stream payloads.',
      priority: probeAvailable ? 'low' : 'medium',
      evidence: [probeAvailable ? `probe_failure=${pct(analytics?.probe_failure_rate)}` : 'probe telemetry unavailable in current slice'],
      dueDate: 'this week',
      snapshotTimestamp,
      baseRankingScore: probeAvailable ? 10 : 55,
      blockedState: probeAvailable ? undefined : blockedStates.probe_health,
      scope: 'observed_slice',
      confidence: probeAvailable && sampleReliability !== 'low' ? 'medium' : 'low',
    }),
  ]), [reliabilityKpi, controlKpi, throughputKpi, probeBlockedKpi, analytics, derived, snapshotTimestamp, sampleReliability, telemetry, probeAvailable, blockedStates])

  const funnelRows = (analytics?.cook_lifecycle_funnel || []).map((row, index, arr) => ({
    ...row,
    label: row.step.replace('_', ' '),
    dropoff_rate: index === 0 ? 0 : Math.max(0, 1 - row.sessions / Math.max(arr[index - 1]?.sessions || 1, 1)),
  }))
  const curveRows = analytics?.pit_temperature_curve || []
  const archetypes = analytics?.session_archetypes || []
  const connectivityRows = analytics?.connectivity_buckets || []
  const firmwareRows = telemetry?.firmware_health || []
  const modelRows = telemetry?.grill_type_health || []
  const issueRows = analytics?.issue_insights || []
  const activeTrendRows = [
    { label: '5m', value: collection?.active_devices_last_5m || 0 },
    { label: '15m', value: collection?.active_devices_last_15m || 0 },
    { label: '60m', value: collection?.active_devices_last_60m || 0 },
    { label: '24h', value: collection?.active_devices_last_24h || 0 },
  ]
  const probeRows = analytics?.probe_usage || []
  const worstInsight = issueRows[0]

  return (
    <div className="page-grid telemetry-page">
      <div className="page-head telemetry-head">
        <div>
          <h2>Product / Engineering</h2>
          <p>Telemetry-backed product analytics for Venom usage, cook failure, control quality, and cohort degradation. Stream-backed where available. No unsupported full-fleet claims.</p>
          <small className="page-meta">API base: {getApiBase()}</small>
        </div>
        <div className="telemetry-status-bar">
          <div className="telemetry-status-item"><small>truth</small><strong>{streamBacked ? 'stream-backed observed slice' : 'fallback / blocked'}</strong></div>
          <div className="telemetry-status-item"><small>sample</small><strong>n {sampleSize} · {sampleReliability}</strong></div>
          <div className="telemetry-status-item"><small>scope</small><strong>{streamBacked ? 'observed_slice' : 'degraded'}</strong></div>
          <div className="telemetry-status-item"><small>last updated</small><strong>{formatTelemetryFreshness(collection?.newest_sample_timestamp_seen)}</strong></div>
        </div>
      </div>

      {loading ? <Card title="Product / Engineering"><div className="state-message">Loading telemetry analytics…</div></Card> : null}
      {error ? <Card title="Product / Engineering Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <div className="four-col telemetry-kpi-grid">
            <MiniKpiCard title="Active Cooks" value={`${derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 0}`} subtext={`5m devices ${derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 0} · median RSSI ${derived?.median_rssi_now ?? '—'} dBm`} link={drillLabel('/analysis/rssi-impact', 'View cooks')} tone={statusTone(derived?.active_cooks_now, 20, 8)} kpi={activeCooksKpi} />
            <MiniKpiCard title="Cook Throughput" value={`${derived?.cooks_started_24h ?? slice?.sessions_derived ?? 0} started / ${derived?.cooks_completed_24h ?? 0} completed`} subtext={`median ${secondsToMinutes(derived?.median_cook_duration_seconds)} · p95 ${secondsToMinutes(derived?.p95_cook_duration_seconds)}`} link={drillLabel('/analysis/cook-failures', 'View funnel')} tone={statusTone((derived?.cooks_completed_24h || 0) / Math.max(derived?.cooks_started_24h || 1, 1), 0.7, 0.45)} kpi={throughputKpi} />
            <MiniKpiCard title="Reliability" value={`${pct(derived?.session_success_rate)} success`} subtext={`disconnect ${pct(derived?.disconnect_proxy_rate)} · timeout ${pct(derived?.timeout_rate)} · probe error ${pct(analytics?.probe_failure_rate)}`} link={drillLabel('/analysis/cook-failures', 'View issues')} tone={statusTone(derived?.session_success_rate, 0.8, 0.65)} kpi={reliabilityKpi} />
            <MiniKpiCard title="Control Quality" value={`${pct(derived?.stability_score)} stable`} subtext={`overshoot ${pct(derived?.overshoot_rate)} · p50 ${secondsToMinutes(derived?.time_to_stabilize_p50_seconds)} · p95 ${secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}`} link={drillLabel('/analysis/temp-curves', 'View curves')} tone={statusTone(derived?.stability_score, 0.8, 0.65)} kpi={controlKpi} />
          </div>

          <DecisionStack actions={actions} />

          <Card title="Cook lifecycle funnel">
            <div className="section-head-row">
              <p>Started → reached target → stable → completed. Stage derivation is estimated from stream-derived sessions; drop-off reasons are proxy-derived where noted.</p>
              {drillLabel('/analysis/cook-failures', 'Open cook failures')}
            </div>
            <div className="two-col-equal">
              <div className="chart-wrap chart-wrap-short">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={funnelRows} layout="vertical" margin={{ left: 20, right: 20, top: 10, bottom: 10 }}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis type="number" stroke="#9fb0d4" />
                    <YAxis type="category" dataKey="label" stroke="#9fb0d4" width={120} />
                    <Tooltip />
                    <Bar dataKey="sessions" radius={[0, 8, 8, 0]}>
                      {funnelRows.map((row, idx) => <Cell key={row.step} fill={['#6ea8ff', '#55c2ff', '#ffb257', '#39d08f'][idx] || '#6ea8ff'} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="stack-list compact">
                {funnelRows.map((row) => (
                  <div className={`list-item status-${row.rate >= 0.75 ? 'good' : row.rate >= 0.5 ? 'warn' : 'bad'}`} key={row.step}>
                    <div className="item-head"><strong>{row.label}</strong><span>{row.sessions}</span></div>
                    <p>{pct(row.rate)} of started sessions. {row.dropoff_rate ? `Stage drop-off ${pct(row.dropoff_rate)}.` : 'Entry stage.'}</p>
                  </div>
                ))}
                <div className="list-item status-muted"><strong>Top drop-off reasons</strong><p>{(analytics?.dropoff_reasons || []).map((row) => `${row.reason.replace(/_/g, ' ')} ${pct(row.rate)}`).join(' · ') || 'No material drop-off reason returned.'}</p></div>
              </div>
            </div>
          </Card>

          <Card title="Temperature Performance">
            <div className="section-head-row">
              <p>Pit temperature vs target, percentile band, stabilization timing, and overshoot/oscillation metrics. Aggregated over the current observed stream slice.</p>
              {drillLabel('/analysis/temp-curves', 'Open temp curves')}
            </div>
            <div className="two-col">
              <div>
                <div className="chart-wrap">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={curveRows}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                      <XAxis dataKey="minute_bucket" stroke="#9fb0d4" label={{ value: 'minutes', position: 'insideBottom', fill: '#9fb0d4' }} />
                      <YAxis stroke="#9fb0d4" label={{ value: 'pit - target °F', angle: -90, position: 'insideLeft', fill: '#9fb0d4' }} />
                      <Tooltip />
                      <Legend />
                      <Area type="monotone" dataKey="p90_temp_delta" stroke="#ffb257" fill="rgba(255,178,87,0.22)" name="p90 Δ" />
                      <Line type="monotone" dataKey="p50_temp_delta" stroke="#6ea8ff" strokeWidth={3} dot={false} name="p50 Δ" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <small className="page-meta">Sample {sampleSize} · {sampleScope}. If thin, treat this as directional only.</small>
              </div>
              <div className="stack-list compact">
                <div className={`list-item status-${statusTone(derived?.stability_score, 0.8, 0.65)}`}><strong>temp_stability_score</strong><p>{pct(derived?.stability_score)} · observed control stability in derived sessions</p></div>
                <div className={`list-item status-${statusTone(derived?.overshoot_rate, 0.05, 0.15, true)}`}><strong>overshoot_rate</strong><p>{pct(derived?.overshoot_rate)} · sessions that exceeded target materially</p></div>
                <div className={`list-item status-${statusTone(derived?.oscillation_rate, 0.08, 0.18, true)}`}><strong>oscillation_rate</strong><p>{pct(derived?.oscillation_rate)} · sessions that reached range but failed to stabilize</p></div>
                <div className="list-item status-neutral"><strong>time_to_stabilize</strong><p>p50 {secondsToMinutes(derived?.time_to_stabilize_p50_seconds)} · p95 {secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}</p></div>
              </div>
            </div>
          </Card>

          <Card title="Session Patterns">
            <div className="section-head-row">
              <p>Heuristic archetypes from stream-derived session shape. Estimated, not canonical clustering.</p>
              {drillLabel('/analysis/session-clusters', 'Open session clusters')}
            </div>
            <div className="four-col">
              {archetypes.map((row) => (
                <div className={`list-item archetype-card status-${row.archetype === 'stable' ? 'good' : row.archetype === 'dropout' ? 'bad' : 'warn'}`} key={row.archetype}>
                  <strong>{row.archetype}</strong>
                  <div className="hero-metric hero-metric-sm">{pct(row.rate)}</div>
                  <p>{row.description}</p>
                  <small>n {row.sessions} · truth_state {analyticsTruthState}</small>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Connectivity / Environment">
            <div className="section-head-row">
              <p>RSSI distribution and observed correlation between weak-signal cohorts and lower reliability. This is correlation / hypothesis, not causation.</p>
              {drillLabel('/analysis/rssi-impact', 'Open RSSI impact')}
            </div>
            <div className="two-col">
              <div className="chart-wrap chart-wrap-medium">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={connectivityRows}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="bucket" stroke="#9fb0d4" />
                    <YAxis yAxisId="left" stroke="#9fb0d4" />
                    <YAxis yAxisId="right" orientation="right" stroke="#9fb0d4" />
                    <Tooltip />
                    <Legend />
                    <Bar yAxisId="left" dataKey="sessions" fill="#6ea8ff" name="sessions" />
                    <Line yAxisId="right" type="monotone" dataKey="failure_rate" stroke="#ff6d7a" strokeWidth={3} dot={false} name="failure rate" />
                    <Line yAxisId="right" type="monotone" dataKey="stability_score" stroke="#39d08f" strokeWidth={3} dot={false} name="stability score" />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="stack-list compact">
                <div className="list-item status-warn"><strong>sessions below -75 dBm</strong><p>{pct(slice?.low_rssi_session_rate)} of derived sessions</p></div>
                <div className="list-item status-neutral"><strong>disconnect proxy by bucket</strong><p>{connectivityRows.map((row) => `${row.bucket}: ${pct(row.disconnect_rate)}`).join(' · ') || 'No bucket data returned.'}</p></div>
                <div className={`list-item status-${worstInsight?.issue?.toLowerCase().includes('connectivity') ? 'bad' : 'muted'}`}><strong>connectivity insight</strong><p>{worstInsight?.issue?.toLowerCase().includes('connectivity') ? `${worstInsight.signal} ${worstInsight.action}` : 'No strong connectivity-linked issue crossed threshold in the current slice.'}</p></div>
              </div>
            </div>
          </Card>

          <Card title="Probe Analytics">
            <div className="section-head-row">
              <p>Only shown where current telemetry actually supports probe-level analysis.</p>
              {drillLabel('/analysis/probe-health', 'Open probe health')}
            </div>
            {probeAvailable ? (
              <div className="two-col">
                <div className="chart-wrap chart-wrap-medium">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={probeRows}>
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" />
                      <XAxis dataKey="probe_count" stroke="#9fb0d4" />
                      <YAxis stroke="#9fb0d4" />
                      <Tooltip />
                      <Legend />
                      <Bar dataKey="sessions" fill="#6ea8ff" name="sessions" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="stack-list compact">
                  <div className="list-item status-neutral"><strong>probe usage mix</strong><p>{probeRows.map((row) => `${row.probe_count}: ${pct(row.rate)} (n=${row.sessions})`).join(' · ')}</p></div>
                  <div className="list-item status-warn"><strong>probe failure rate</strong><p>{pct(analytics?.probe_failure_rate)}</p></div>
                  <div className="list-item status-neutral"><strong>pit vs probe delta</strong><p>{analytics?.pit_probe_delta_avg !== null && analytics?.pit_probe_delta_avg !== undefined ? `${analytics.pit_probe_delta_avg}° avg absolute delta` : 'Unavailable'}</p></div>
                </div>
              </div>
            ) : (
              <div className="list-item status-bad">
                <strong>{blockedStates.probe_health.decision_blocked}</strong>
                <p>{blockedStates.probe_health.missing_source}</p>
                <small><strong>still trustworthy:</strong> {blockedStates.probe_health.still_trustworthy.join(', ')}</small>
                <small><strong>owner:</strong> {blockedStates.probe_health.owner} · <strong>next action:</strong> {blockedStates.probe_health.required_action_to_unblock}</small>
              </div>
            )}
          </Card>

          <Card title="Cohort Comparison">
            <div className="section-head-row">
              <p>Firmware and model cohorts with explicit n, failure, stability proxy, disconnect, and severity.</p>
              {drillLabel('/analysis/firmware-model', 'Open firmware/model analysis')}
            </div>
            <div className="two-col">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Firmware</th><th>n</th><th>success</th><th>disconnect</th><th>failure</th><th>health</th><th>severity</th></tr>
                  </thead>
                  <tbody>
                    {firmwareRows.slice(0, 8).map((row) => (
                      <tr key={row.key}>
                        <td>{row.key}</td><td>{row.sessions}</td><td>{pct(1 - row.failure_rate)}</td><td>{pct(row.disconnect_rate)}</td><td>{pct(row.failure_rate)}</td><td>{pct(row.health_score)}</td><td>{row.severity}{row.sessions < 3 ? ' · low n' : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Model</th><th>n</th><th>success</th><th>disconnect</th><th>failure</th><th>health</th><th>severity</th></tr>
                  </thead>
                  <tbody>
                    {modelRows.slice(0, 8).map((row) => (
                      <tr key={row.key}>
                        <td>{row.key}</td><td>{row.sessions}</td><td>{pct(1 - row.failure_rate)}</td><td>{pct(row.disconnect_rate)}</td><td>{pct(row.failure_rate)}</td><td>{pct(row.health_score)}</td><td>{row.severity}{row.sessions < 3 ? ' · low n' : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </Card>

          <Card title="Automated Product Insights">
            <div className="section-head-row">
              <p>Prioritized issue cards ranked by severity, sample reliability, recurrence, cohort concentration, and testability. Low reliability stays investigative.</p>
            </div>
            <div className="stack-list compact">
              {issueRows.map((row, index) => (
                <div className={`list-item status-${row.confidence === 'high' ? 'bad' : row.confidence === 'medium' ? 'warn' : 'muted'}`} key={`${row.issue}-${index}`}>
                  <div className="item-head"><strong>{row.issue}</strong><span className="badge badge-neutral">{row.confidence}</span></div>
                  <p>{row.signal}</p>
                  <small><strong>cohort:</strong> {row.cohort} · <strong>scope:</strong> observed_slice</small>
                  <small><strong>recommended action:</strong> {row.action}</small>
                  <small><strong>drill-down:</strong> {row.issue.toLowerCase().includes('connectivity') ? '/analysis/rssi-impact' : row.issue.toLowerCase().includes('firmware') ? '/analysis/firmware-model' : '/analysis/temp-curves'}</small>
                </div>
              ))}
              {!issueRows.length ? <div className="state-message">No issue card crossed threshold in the current slice.</div> : null}
            </div>
          </Card>

          <Card title="Truth / confidence guardrails">
            <div className="stack-list compact">
              <div className="list-item status-muted"><strong>sample scope</strong><p>{sampleScope}</p></div>
              <div className="list-item status-neutral"><strong>truth_state handling</strong><p>Top KPI strip and analytics sections keep `truth_state`, `sample_size`, and `sample_reliability`. Stream-backed analytics are shown as estimated/proxy rather than canonical truth.</p></div>
              <div className="list-item status-bad"><strong>{blockedStates.generalization.decision_blocked}</strong><p>{blockedStates.generalization.missing_source}</p><small><strong>still trustworthy:</strong> {blockedStates.generalization.still_trustworthy.join(', ')}</small><small><strong>next action:</strong> {blockedStates.generalization.required_action_to_unblock}</small></div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
