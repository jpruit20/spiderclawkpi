import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { DecisionStack } from '../components/DecisionStack'
import { ApiError, api, getApiBase } from '../lib/api'
import { ActionObject, BlockedStateOutput, KPIObject, TelemetrySummary } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildNumericKpi, buildTextKpi, enforceActionContract, RankedActionObject } from '../lib/divisionContract'

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
  const confidence = telemetry?.confidence || null
  const boundedTruthState = latest ? 'proxy' : 'blocked'
  const reliabilityTruthState = latest ? 'estimated' : 'blocked'
  const sampleSize = Math.max(collection?.distinct_devices_observed || 0, slice?.sessions_derived || 0)
  const sampleScope = `${collection?.distinct_devices_observed || 0} device(s), ${collection?.samples_retained || 0} samples, bounded scan`
  const sampleReliability: KPIObject['sample_reliability'] = sampleSize <= 1 || collection?.scan_truncated || collection?.max_record_cap_hit ? 'low' : sampleSize < 10 ? 'medium' : 'high'
  const limitedSampleNote = sampleReliability === 'low' ? 'Limited sample — directional only' : null

  const kpis: KPIObject[] = useMemo(() => [
    buildNumericKpi({ key: 'product_distinct_devices_observed', currentValue: collection?.distinct_devices_observed ?? null, targetValue: null, priorValue: null, owner: 'Kyle', truthState: boundedTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_distinct_engaged_devices_observed', currentValue: collection?.distinct_engaged_devices_observed ?? null, targetValue: null, priorValue: null, owner: 'Kyle', truthState: boundedTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_sessions_derived', currentValue: slice?.sessions_derived ?? null, targetValue: null, priorValue: null, owner: 'Kyle', truthState: reliabilityTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildNumericKpi({ key: 'product_median_session_duration_minutes', currentValue: slice ? slice.median_session_duration_seconds / 60 : null, targetValue: null, priorValue: null, owner: 'Kyle', truthState: reliabilityTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildTextKpi({ key: 'product_low_rssi_session_risk', currentValue: slice ? (sampleReliability === 'low' ? `${Math.round(slice.low_rssi_session_rate * 100)}% of ${slice.sessions_derived} observed session(s) show low RSSI risk. ${limitedSampleNote}` : `${Math.round(slice.low_rssi_session_rate * 100)}% of observed sessions show low RSSI risk`) : null, targetValue: 'Low observed low-RSSI risk', owner: 'Kyle', status: (slice?.low_rssi_session_rate || 0) >= 0.2 ? 'red' : 'yellow', truthState: reliabilityTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildTextKpi({ key: 'product_error_vector_presence', currentValue: slice ? (sampleReliability === 'low' ? `${Math.round(slice.error_vector_presence_rate * 100)}% of ${slice.sessions_derived} observed session(s) show non-zero error vectors. ${limitedSampleNote}` : `${Math.round(slice.error_vector_presence_rate * 100)}% of observed sessions show non-zero error vectors`) : null, targetValue: 'Low observed error-vector presence', owner: 'Kyle', status: (slice?.error_vector_presence_rate || 0) > 0 ? 'yellow' : 'green', truthState: reliabilityTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
    buildTextKpi({ key: 'product_coverage_quality', currentValue: collection?.coverage_summary || 'No telemetry coverage summary', targetValue: 'Broad trustworthy observed slice', owner: 'Joseph', status: collection?.scan_truncated || collection?.max_record_cap_hit ? 'red' : 'yellow', truthState: boundedTruthState, lastUpdated: snapshotTimestamp, sampleSize, sampleScope, sampleReliability }),
  ], [collection, slice, snapshotTimestamp, boundedTruthState, reliabilityTruthState, sampleSize, sampleScope, sampleReliability, limitedSampleNote])

  const blockedStates: Record<string, BlockedStateOutput> = {
    product_coverage_quality: buildBlockedState({
      decision_blocked: 'Whether observed telemetry can be treated as representative of the full fleet',
      missing_source: 'global recent-time fleet access path',
      still_trustworthy: ['device-local ordering', 'observed slice cohorts', 'bounded telemetry health summary'],
      owner: 'Joseph',
      required_action_to_unblock: 'Keep product decisions scoped to the observed slice until telemetry access broadens beyond bounded device-keyed reads.',
    }),
  }

  const actions: RankedActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'product-review-reliability-slice',
      triggerKpi: kpis[4],
      triggerCondition: 'observed low RSSI or reliability risk in current slice',
      owner: 'Kyle',
      requiredAction: sampleSize < 3 ? 'Investigate the observed low-signal slice further before scaling the conclusion beyond the current observed sample.' : 'Review the observed low-signal and reliability slice by firmware/model before treating the issue as fleet-wide.',
      priority: (slice?.low_rssi_session_rate || 0) >= 0.2 ? 'critical' : 'high',
      evidence: ['telemetry slice snapshot', 'firmware cohort summary', 'model cohort summary'],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Math.round((slice?.low_rssi_session_rate || 0) * 100) + 55,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : sampleReliability === 'medium' ? 'medium' : 'high',
    }),
    actionFromKpi({
      id: 'product-review-error-slice',
      triggerKpi: kpis[5],
      triggerCondition: 'error-vector presence observed in derived session slice',
      owner: 'Kyle',
      requiredAction: sampleSize < 3 ? 'Investigate the observed error-vector slice further before scaling the conclusion beyond the current observed sample.' : 'Inspect the observed error-vector cohort and compare firmware/model concentration before escalating to firmware remediation.',
      priority: (slice?.error_vector_presence_rate || 0) > 0 ? 'high' : 'medium',
      evidence: ['telemetry error vectors', 'top error codes', 'firmware cohorts'],
      dueDate: '48h',
      snapshotTimestamp,
      baseRankingScore: Math.round((slice?.error_vector_presence_rate || 0) * 100) + 45,
      scope: 'observed_slice',
      confidence: sampleReliability === 'low' ? 'low' : sampleReliability === 'medium' ? 'medium' : 'high',
    }),
    actionFromKpi({
      id: 'product-bound-coverage-warning',
      triggerKpi: kpis[6],
      triggerCondition: 'coverage summary indicates bounded/truncated read',
      owner: 'Joseph',
      coOwner: 'Kyle',
      requiredAction: 'Use telemetry for observed-slice prioritization only; do not convert bounded slice findings into full-fleet claims.',
      priority: 'critical',
      evidence: [collection?.coverage_summary || 'bounded telemetry coverage'],
      dueDate: 'now',
      snapshotTimestamp,
      baseRankingScore: collection?.scan_truncated || collection?.max_record_cap_hit ? 95 : 40,
      blockedState: blockedStates.product_coverage_quality,
      scope: 'observed_slice',
      confidence: 'low',
    }),
  ]).slice(0, 5)

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Product / Engineering</h2>
        <p>Telemetry-backed product reliability view for the observed slice only. No full-fleet claims.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Product / Engineering"><div className="state-message">Loading telemetry operating view…</div></Card> : null}
      {error ? <Card title="Product / Engineering Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Telemetry health / coverage snapshot"><div className="hero-metric">{collection?.distinct_devices_observed ?? 0}</div><div className="state-message">distinct devices observed · truth {confidence?.global_completeness || 'unknown'} · sample {sampleReliability}</div></Card>
            <Card title="Observed device and session slice"><div className="hero-metric">{slice?.sessions_derived ?? 0}</div><div className="state-message">derived sessions · median {(slice?.median_session_duration_seconds || 0 / 60).toFixed ? ((slice?.median_session_duration_seconds || 0) / 60).toFixed(1) : 0} min</div></Card>
            <Card title="Reliability indicators"><div className="hero-metric">{latest ? `${(latest.session_reliability_score * 100).toFixed(0)}%` : '—'}</div><div className="state-message">observed slice reliability score</div></Card>
          </div>
          <DecisionStack actions={actions} />
          <div className="two-col">
            <Card title="Telemetry health / coverage snapshot">
              <div className="stack-list compact">
                <div className="list-item status-warn"><strong>coverage summary</strong><p>{collection?.coverage_summary || 'No telemetry coverage summary returned.'}</p><small><strong>oldest:</strong> {collection?.oldest_sample_timestamp_seen || 'n/a'} · <strong>newest:</strong> {collection?.newest_sample_timestamp_seen || 'n/a'}</small></div>
                <div className="list-item status-muted"><strong>source truth</strong><p>Direct DynamoDB read from `sg_device_shadows` in the observed bounded slice.</p><small><strong>max cap hit:</strong> {String(collection?.max_record_cap_hit ?? false)} · <strong>scan truncated:</strong> {String(collection?.scan_truncated ?? false)} · <strong>gap timeout:</strong> {collection?.session_gap_timeout_minutes ?? 'n/a'} min</small></div>
              </div>
            </Card>
            <Card title="Observed device and session slice">
              <div className="stack-list compact">
                <div className="list-item status-neutral"><strong>device slice</strong><p>Distinct devices observed: {collection?.distinct_devices_observed ?? 0} · engaged devices: {collection?.distinct_engaged_devices_observed ?? 0}</p></div>
                <div className="list-item status-neutral"><strong>session slice</strong><p>Sessions derived: {slice?.sessions_derived ?? 0} · average duration: {slice ? (slice.average_session_duration_seconds / 60).toFixed(1) : '0.0'} min · median duration: {slice ? (slice.median_session_duration_seconds / 60).toFixed(1) : '0.0'} min</p><small><strong>sample scope:</strong> {sampleScope} · <strong>sample reliability:</strong> {sampleReliability}</small></div>
              </div>
            </Card>
          </div>
          <div className="two-col">
            <Card title="Firmware / model cohort summary">
              <div className="stack-list">
                {(telemetry?.firmware_health || []).slice(0, 5).map((row) => <div className={`list-item status-${row.severity === 'high' ? 'bad' : row.severity === 'medium' ? 'warn' : 'good'}`} key={`fw-${row.key}`}><strong>Firmware {row.key}</strong><p>Sessions {row.sessions} · failure {(row.failure_rate * 100).toFixed(1)}% · disconnect {(row.disconnect_rate * 100).toFixed(1)}%</p></div>)}
                {(telemetry?.grill_type_health || []).slice(0, 5).map((row) => <div className={`list-item status-${row.severity === 'high' ? 'bad' : row.severity === 'medium' ? 'warn' : 'good'}`} key={`gt-${row.key}`}><strong>Model {row.key}</strong><p>Sessions {row.sessions} · failure {(row.failure_rate * 100).toFixed(1)}% · disconnect {(row.disconnect_rate * 100).toFixed(1)}%</p></div>)}
                {!(telemetry?.firmware_health || []).length && !(telemetry?.grill_type_health || []).length ? <div className="state-message">No cohort rows returned.</div> : null}
              </div>
            </Card>
            <Card title="Reliability indicators from observed data">
              <div className="stack-list compact">
                <div className="list-item status-warn"><strong>low signal risk proxy</strong><p>{kpis[4]?.current_value || 'No slice returned'}</p><small><strong>truth_state:</strong> estimated · <strong>sample size:</strong> {kpis[4]?.sample_size ?? 'n/a'} · <strong>sample reliability:</strong> {kpis[4]?.sample_reliability || 'n/a'}</small></div>
                <div className="list-item status-warn"><strong>error-vector presence rate</strong><p>{kpis[5]?.current_value || 'No slice returned'}</p><small><strong>truth_state:</strong> estimated · <strong>sample size:</strong> {kpis[5]?.sample_size ?? 'n/a'} · <strong>sample reliability:</strong> {kpis[5]?.sample_reliability || 'n/a'}</small></div>
                <div className="list-item status-neutral"><strong>target temp distribution</strong><p>{slice?.target_temp_distribution?.map((row) => `${row.target_temp}°:${row.count}`).join(' · ') || 'No target-temp distribution returned.'}</p></div>
              </div>
            </Card>
          </div>
          <Card title="Blocked-state panels">
            <div className="stack-list compact">
              <div className="list-item status-bad"><strong>{blockedStates.product_coverage_quality.decision_blocked}</strong><p>{blockedStates.product_coverage_quality.missing_source}</p><small><strong>still trustworthy:</strong> {blockedStates.product_coverage_quality.still_trustworthy.join(', ')}</small><small><strong>owner:</strong> {blockedStates.product_coverage_quality.owner} · <strong>next action:</strong> {blockedStates.product_coverage_quality.required_action_to_unblock}</small></div>
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
