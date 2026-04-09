import { ReactNode, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { BlockedStateOutput, KPIObject, TelemetrySummary } from '../lib/types'

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

function listText(items: Array<string | null | undefined>) {
  const filtered = items.filter((item): item is string => Boolean(item && item.trim()))
  return filtered.length ? filtered : ['No current row data returned.']
}

function drillLabel(path: string, label: string) {
  return <Link className="analysis-link" to={path}>{label} →</Link>
}

type TelemetryBoardCell = {
  label: string
  heading: string
  bullets: string[]
  purpose?: string
  footer?: ReactNode
}

type TelemetryBoardRowData = {
  id: string
  title: string
  section: string
  cells: TelemetryBoardCell[]
}

function BoardCell({ cell }: { cell: TelemetryBoardCell }) {
  return (
    <div className="telemetry-board-cell">
      <div className="telemetry-board-cell-label">{cell.label}</div>
      <div className="telemetry-board-cell-heading">{cell.heading}</div>
      <ul className="telemetry-board-list">
        {cell.bullets.map((bullet, index) => <li key={`${cell.label}-${index}`}>{bullet}</li>)}
      </ul>
      {cell.purpose ? <p className="telemetry-board-purpose">{cell.purpose}</p> : null}
      {cell.footer ? <div className="telemetry-board-footer">{cell.footer}</div> : null}
    </div>
  )
}

function BoardRow({ row }: { row: TelemetryBoardRowData }) {
  return (
    <section className="telemetry-board-row">
      <div className="telemetry-board-row-title">
        <small>{row.id}</small>
        <strong>{row.title}</strong>
      </div>
      <div className="telemetry-board-grid">
        {row.cells.map((cell) => <BoardCell key={`${row.id}-${cell.label}`} cell={cell} />)}
      </div>
    </section>
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

  const latest = telemetry?.latest || null
  const slice = telemetry?.slice_snapshot || null
  const collection = telemetry?.collection_metadata || null
  const confidence = telemetry?.confidence || null
  const analytics = telemetry?.analytics || null
  const derived = analytics?.derived_metrics || null
  const streamBacked = collection?.sample_source === 'dynamodb_stream'
  const sampleSize = Math.max(slice?.sessions_derived || 0, collection?.distinct_devices_observed || 0, collection?.active_devices_last_15m || 0)
  const sampleReliability: KPIObject['sample_reliability'] = !streamBacked ? 'low' : sampleSize < 5 ? 'low' : sampleSize < 20 ? 'medium' : 'high'
  const sampleScope = streamBacked
    ? `${collection?.distinct_devices_observed || 0} devices · ${slice?.sessions_derived || 0} derived sessions · ${collection?.records_loaded || 0} stream rows · latest ${formatTelemetryFreshness(collection?.newest_sample_timestamp_seen)}`
    : `${collection?.distinct_devices_observed || 0} devices from fallback telemetry — directional only`
  const truthState = streamBacked ? 'observed_slice stream-backed' : 'fallback / blocked'
  const analyticsTruthState = streamBacked ? 'estimated / proxy' : 'blocked / degraded'
  const funnelRows = analytics?.cook_lifecycle_funnel || []
  const dropoffRows = analytics?.dropoff_reasons || []
  const curveRows = analytics?.pit_temperature_curve || []
  const archetypes = analytics?.session_archetypes || []
  const connectivityRows = analytics?.connectivity_buckets || []
  const probeRows = analytics?.probe_usage || []
  const issueRows = analytics?.issue_insights || []
  const firmwareRows = telemetry?.firmware_health || []
  const modelRows = telemetry?.grill_type_health || []
  const probeAvailable = Boolean(probeRows.some((row) => row.probe_count > 0) || (analytics?.pit_probe_delta_avg !== null && analytics?.pit_probe_delta_avg !== undefined))

  const blockedStates: Record<string, BlockedStateOutput> = {
    probe_health: {
      decision_blocked: 'Probe-health conclusions at fleet level',
      missing_source: 'consistent probe telemetry fields in the current raw stream payload',
      still_trustworthy: ['active cooks', 'cook lifecycle funnel', 'temperature control quality', 'connectivity correlation', 'firmware/model cohorts'],
      owner: 'Kyle',
      required_action_to_unblock: 'Confirm stable ingestion of probe telemetry fields across stream rows before turning probe analytics into a primary decision surface.',
    },
    generalization: {
      decision_blocked: 'Full-fleet product truth from this page',
      missing_source: streamBacked ? 'canonical cook ledger / historical backfill' : 'live stream-backed telemetry path',
      still_trustworthy: ['observed_slice product patterns', 'recent activity windows', 'cohort comparisons with explicit n', 'proxy-based issue detection'],
      owner: 'Joseph',
      required_action_to_unblock: streamBacked ? 'Keep this page scoped to observed slice telemetry until historical/canonical cook truth is added.' : 'Restore stream-backed telemetry before making product decisions from this page.',
    },
  }

  const rows = useMemo<TelemetryBoardRowData[]>(() => {
    const row01: TelemetryBoardRowData = {
      id: 'Row 01',
      title: 'Top KPI Strip',
      section: 'Core overview',
      cells: [
        {
          label: 'UI Component',
          heading: 'Top KPI Strip',
          bullets: ['Active Cooks', 'Cook Throughput', 'Reliability', 'Control Quality'],
          purpose: 'Fast read on current usage, throughput, reliability, and control behavior.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Primary sources and fields',
          bullets: listText([
            'telemetry summary.latest',
            'telemetry summary.slice_snapshot',
            'telemetry_sessions',
            'telemetry_daily',
            'telemetry_stream_events (indirect)',
            `active_cooks_now = ${derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 'n/a'}`,
            `devices_reporting_last_5m = ${derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 'n/a'}`,
            `median_rssi_now = ${derived?.median_rssi_now ?? 'n/a'}`,
            `cooks_started_24h = ${derived?.cooks_started_24h ?? slice?.sessions_derived ?? 'n/a'}`,
            `cooks_completed_24h = ${derived?.cooks_completed_24h ?? 'n/a'}`,
            `session_success_rate = ${pct(derived?.session_success_rate ?? latest?.session_reliability_score)}`,
            `disconnect_proxy_rate = ${pct(derived?.disconnect_proxy_rate ?? latest?.disconnect_rate, 1)}`,
            `stability_score = ${pct(derived?.stability_score ?? latest?.temp_stability_score)}`,
            `overshoot_rate = ${pct(derived?.overshoot_rate, 1)}`,
            `time_to_stabilize_p50_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p50_seconds)}`,
            `time_to_stabilize_p95_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}`,
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed KPIs',
          bullets: listText([
            `active_cooks_now = ${derived?.active_cooks_now ?? collection?.active_devices_last_15m ?? 0}`,
            `devices_reporting_last_5m = ${derived?.devices_reporting_last_5m ?? collection?.active_devices_last_5m ?? 0}`,
            `cooks_started_24h = ${derived?.cooks_started_24h ?? slice?.sessions_derived ?? 0}`,
            `cooks_completed_24h = ${derived?.cooks_completed_24h ?? 0}`,
            `median_cook_duration_seconds = ${secondsToMinutes(derived?.median_cook_duration_seconds)}`,
            `p95_cook_duration_seconds = ${secondsToMinutes(derived?.p95_cook_duration_seconds)}`,
            `session_success_rate = ${pct(derived?.session_success_rate ?? latest?.session_reliability_score)}`,
            `disconnect_proxy_rate = ${pct(derived?.disconnect_proxy_rate, 1)}`,
            `timeout_rate = ${pct(derived?.timeout_rate, 1)}`,
            `probe_error_rate = ${pct(analytics?.probe_failure_rate, 1)}`,
            `stability_score = ${pct(derived?.stability_score)}`,
            `overshoot_rate = ${pct(derived?.overshoot_rate, 1)}`,
            `time_to_stabilize_p50_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p50_seconds)}`,
            `time_to_stabilize_p95_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}`,
          ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            `truth_state = ${analyticsTruthState}`,
            'proxy for live activity / coverage',
            'estimated for session-derived reliability/control metrics',
            `sample_size = ${sampleSize}`,
            `sample_scope = ${sampleScope}`,
            `sample_reliability = ${sampleReliability}`,
            'never show naked percentages without n',
            sampleReliability === 'low' ? 'thin sample: directional only' : 'sample strength acceptable for observed-slice decision support',
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Drill-downs and decisions',
          bullets: ['View cooks', 'View funnel', 'View issues', 'View curves', 'Is usage healthy?', 'Is reliability degrading?', 'Is control quality weak?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/rssi-impact', 'View cooks')}{drillLabel('/analysis/cook-failures', 'View funnel')}{drillLabel('/analysis/temp-curves', 'View curves')}</div>,
        },
      ],
    }

    const row02: TelemetryBoardRowData = {
      id: 'Row 02',
      title: 'Cook Lifecycle Funnel',
      section: 'Core overview',
      cells: [
        {
          label: 'UI Component',
          heading: 'Cook Lifecycle Funnel',
          bullets: ['Started', 'Reached Target', 'Stable', 'Completed'],
          purpose: 'Show where cooks fail and where drop-off occurs.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and derivation logic',
          bullets: listText([
            'telemetry_sessions',
            'telemetry summary.latest',
            'session state derivation logic',
            'engaged flags',
            'timestamps',
            'stability logic',
            'completion logic',
            'proxy failure reasons',
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Funnel metrics',
          bullets: listText([
            ...funnelRows.map((row) => `${row.step.replace(/_/g, ' ')} = ${row.sessions} (${pct(row.rate)})`),
            ...dropoffRows.slice(0, 4).map((row) => `${row.reason.replace(/_/g, ' ')} dropoff = ${row.sessions} (${pct(row.rate)})`),
          ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            'estimated for funnel stages',
            'proxy for inferred dropoff reasons',
            `show n at each stage = ${sampleSize}`,
            dropoffRows.length ? 'reason labels are heuristic and should stay clearly labeled' : 'no strong dropoff reason currently returned',
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: ['Where do cooks fail?', 'What failure mode is growing?', 'Should Kyle investigate control, connectivity, or probe behavior?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/cook-failures', 'Open cook failures')}</div>,
        },
      ],
    }

    const row03: TelemetryBoardRowData = {
      id: 'Row 03',
      title: 'Temperature Performance',
      section: 'Behavioral analytics',
      cells: [
        {
          label: 'UI Component',
          heading: 'Temperature Performance',
          bullets: ['Pit vs target curve', 'p50 / p90 deviation band', 'Stability / overshoot summaries'],
          purpose: 'Show whether control quality and stabilization are healthy.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'analytics.pit_temperature_curve',
            'analytics.derived_metrics',
            `curve points = ${curveRows.length}`,
            `stability_score = ${pct(derived?.stability_score)}`,
            `overshoot_rate = ${pct(derived?.overshoot_rate, 1)}`,
            `oscillation_rate = ${pct(derived?.oscillation_rate, 1)}`,
            `time_to_stabilize_p50_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p50_seconds)}`,
            `time_to_stabilize_p95_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}`,
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: listText([
            `temp_stability_score = ${pct(derived?.stability_score)}`,
            `overshoot_rate = ${pct(derived?.overshoot_rate, 1)}`,
            `oscillation_rate = ${pct(derived?.oscillation_rate, 1)}`,
            `time_to_stabilize_p50_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p50_seconds)}`,
            `time_to_stabilize_p95_seconds = ${secondsToMinutes(derived?.time_to_stabilize_p95_seconds)}`,
            curveRows[0] ? `first curve bucket = minute ${curveRows[0].minute_bucket} / p50 ${curveRows[0].p50_temp_delta ?? '—'}°` : null,
          ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            `truth_state = ${analyticsTruthState}`,
            `sample_scope = ${sampleScope}`,
            sampleReliability === 'low' ? 'thin sample: directional only' : 'safe for observed-slice control-quality review',
            'temperature deltas are slice-based summaries, not full-fleet truth',
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: ['Is control unstable?', 'Is overshoot worsening?', 'Should temperature behavior drive product or firmware investigation?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/temp-curves', 'Open temp curves')}</div>,
        },
      ],
    }

    const row04: TelemetryBoardRowData = {
      id: 'Row 04',
      title: 'Session Patterns',
      section: 'Behavioral analytics',
      cells: [
        {
          label: 'UI Component',
          heading: 'Session Patterns',
          bullets: ['Stable', 'Dropout', 'Interrupted', 'Heuristic archetypes'],
          purpose: 'Show the dominant observed session shapes in the current telemetry slice.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'analytics.session_archetypes',
            `archetype rows = ${archetypes.length}`,
            ...archetypes.map((row) => `${row.archetype} sessions = ${row.sessions}`),
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: listText(archetypes.map((row) => `${row.archetype} = ${pct(row.rate)} (n=${row.sessions})`)),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            'estimated heuristic clustering only',
            'not canonical session taxonomy',
            `sample_reliability = ${sampleReliability}`,
            `sample_size = ${sampleSize}`,
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: ['Which session shape is dominating?', 'Are unstable archetypes growing?', 'Should cluster behavior reshape deeper analysis priority?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/session-clusters', 'Open session clusters')}</div>,
        },
      ],
    }

    const row05: TelemetryBoardRowData = {
      id: 'Row 05',
      title: 'Connectivity / Environment',
      section: 'Behavioral analytics',
      cells: [
        {
          label: 'UI Component',
          heading: 'Connectivity / Environment',
          bullets: ['RSSI buckets', 'Failure correlation', 'Disconnect concentration'],
          purpose: 'Show whether weak-signal cohorts align with worse outcomes.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'analytics.connectivity_buckets',
            'slice_snapshot.low_rssi_session_rate',
            ...connectivityRows.slice(0, 5).map((row) => `${row.bucket} sessions = ${row.sessions}`),
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: listText([
            `low_rssi_session_rate = ${pct(slice?.low_rssi_session_rate)}`,
            ...connectivityRows.slice(0, 5).map((row) => `${row.bucket}: fail ${pct(row.failure_rate)} · disconnect ${pct(row.disconnect_rate, 1)} · stability ${pct(row.stability_score)}`),
          ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            'correlation / hypothesis, not causation',
            'bucket analysis is observed-slice only',
            `sample_reliability = ${sampleReliability}`,
            'keep weak-signal claims labeled as correlation until corroborated',
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: ['Is weak RSSI a likely driver?', 'Which bucket is highest risk?', 'Should connectivity investigation jump priority?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/rssi-impact', 'Open RSSI impact')}</div>,
        },
      ],
    }

    const row06: TelemetryBoardRowData = {
      id: 'Row 06',
      title: 'Probe Analytics',
      section: 'Segment analysis',
      cells: [
        {
          label: 'UI Component',
          heading: 'Probe Analytics',
          bullets: ['Probe usage mix', 'Probe failure rate', 'Pit vs probe delta'],
          purpose: 'Surface probe-related insights only where telemetry supports them.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'analytics.probe_usage',
            `probe_failure_rate = ${pct(analytics?.probe_failure_rate, 1)}`,
            `pit_probe_delta_avg = ${analytics?.pit_probe_delta_avg ?? 'n/a'}°`,
            ...probeRows.map((row) => `${row.probe_count} probes = ${row.sessions} sessions`),
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: probeAvailable
            ? listText([
                `probe_failure_rate = ${pct(analytics?.probe_failure_rate, 1)}`,
                `pit_probe_delta_avg = ${analytics?.pit_probe_delta_avg ?? 'n/a'}°`,
                ...probeRows.map((row) => `${row.probe_count} probes = ${pct(row.rate)} (n=${row.sessions})`),
              ])
            : listText([
                blockedStates.probe_health.decision_blocked,
                blockedStates.probe_health.missing_source,
              ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: probeAvailable
            ? listText([
                `truth_state = ${analyticsTruthState}`,
                `sample_reliability = ${sampleReliability}`,
                'probe analytics remain observed-slice only',
              ])
            : listText([
                'truth_state = blocked',
                `owner = ${blockedStates.probe_health.owner}`,
                `still trustworthy = ${blockedStates.probe_health.still_trustworthy.join(', ')}`,
              ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: probeAvailable
            ? ['Is probe failure rising?', 'Is probe count mix changing?', 'Does probe behavior deserve deeper review?']
            : ['Do not generalize probe conclusions yet', 'Unblock probe telemetry coverage first'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/probe-health', 'Open probe health')}</div>,
        },
      ],
    }

    const row07: TelemetryBoardRowData = {
      id: 'Row 07',
      title: 'Cohort Comparison',
      section: 'Segment analysis',
      cells: [
        {
          label: 'UI Component',
          heading: 'Cohort Comparison',
          bullets: ['Firmware cohorts', 'Model cohorts', 'Explicit n and severity'],
          purpose: 'Show where degradation is concentrated by firmware or model.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'telemetry.firmware_health',
            'telemetry.grill_type_health',
            ...firmwareRows.slice(0, 4).map((row) => `firmware ${row.key} sessions = ${row.sessions}`),
            ...modelRows.slice(0, 4).map((row) => `model ${row.key} sessions = ${row.sessions}`),
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: listText([
            ...firmwareRows.slice(0, 4).map((row) => `firmware ${row.key}: fail ${pct(row.failure_rate)} · disconnect ${pct(row.disconnect_rate)} · health ${pct(row.health_score)}`),
            ...modelRows.slice(0, 4).map((row) => `model ${row.key}: fail ${pct(row.failure_rate)} · disconnect ${pct(row.disconnect_rate)} · health ${pct(row.health_score)}`),
          ]),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            `truth_state = ${analyticsTruthState}`,
            'cohort cuts require explicit n and low-n labeling',
            'observed_slice only — not full installed-base truth',
            blockedStates.generalization.decision_blocked,
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: ['Which firmware is worst?', 'Which model is drifting?', 'Should cohort degradation trigger product or firmware action?'],
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/firmware-model', 'Open firmware/model analysis')}</div>,
        },
      ],
    }

    const row08: TelemetryBoardRowData = {
      id: 'Row 08',
      title: 'Automated Product Insights',
      section: 'Decision layer',
      cells: [
        {
          label: 'UI Component',
          heading: 'Automated Product Insights',
          bullets: ['Prioritized issue cards', 'Confidence-aware ranking', 'Recommended next action'],
          purpose: 'Translate telemetry evidence into a decision-ready product insight layer.',
        },
        {
          label: 'Data Source / Backend Field',
          heading: 'Sources and fields',
          bullets: listText([
            'analytics.issue_insights',
            ...issueRows.slice(0, 5).map((row) => `${row.issue} · cohort ${row.cohort} · confidence ${row.confidence}`),
          ]),
        },
        {
          label: 'KPI / Derived Metric',
          heading: 'Displayed metrics',
          bullets: listText(issueRows.slice(0, 5).map((row) => `${row.issue}: ${row.signal}`)),
        },
        {
          label: 'Truth / Sample Context',
          heading: 'Truth framing',
          bullets: listText([
            'low-confidence insights stay investigative',
            `sample_reliability = ${sampleReliability}`,
            `session_derivation = ${confidence?.session_derivation || 'unknown'}`,
            `global_completeness = ${confidence?.global_completeness || 'unknown'}`,
          ]),
        },
        {
          label: 'Action / Drill-down',
          heading: 'Primary decisions',
          bullets: listText(issueRows.slice(0, 4).map((row) => row.action)),
          footer: <div className="telemetry-board-links">{drillLabel('/analysis/cook-failures', 'Failure analysis')}{drillLabel('/analysis/temp-curves', 'Curve analysis')}{drillLabel('/analysis/rssi-impact', 'RSSI analysis')}</div>,
        },
      ],
    }

    return [row01, row02, row03, row04, row05, row06, row07, row08]
  }, [analytics, analyticsTruthState, blockedStates.generalization.decision_blocked, blockedStates.probe_health, collection?.active_devices_last_15m, collection?.active_devices_last_5m, confidence?.global_completeness, confidence?.session_derivation, curveRows, derived, dropoffRows, funnelRows, issueRows, latest?.disconnect_rate, latest?.session_reliability_score, latest?.temp_stability_score, modelRows, probeAvailable, probeRows, sampleReliability, sampleScope, sampleSize, slice?.sessions_derived, streamBacked, telemetry?.grill_type_health, telemetry?.firmware_health])

  const groupedRows = [
    { title: 'Core overview', rows: rows.filter((row) => row.section === 'Core overview') },
    { title: 'Behavioral analytics', rows: rows.filter((row) => row.section === 'Behavioral analytics') },
    { title: 'Segment analysis', rows: rows.filter((row) => row.section === 'Segment analysis') },
    { title: 'Decision layer', rows: rows.filter((row) => row.section === 'Decision layer') },
  ]

  return (
    <div className="page-grid telemetry-page telemetry-board-page">
      <div className="page-head telemetry-head">
        <div>
          <h2>Product / Engineering</h2>
          <p>Telemetry-backed product analytics restructured into an 8-row operating board: each row maps the UI component, backend source, KPI layer, truth framing, and drill-down action.</p>
          <small className="page-meta">API base: {getApiBase()}</small>
        </div>
        <div className="telemetry-status-bar">
          <div className="telemetry-status-item"><small>truth</small><strong>{truthState}</strong></div>
          <div className="telemetry-status-item"><small>sample</small><strong>n {sampleSize} · {sampleReliability}</strong></div>
          <div className="telemetry-status-item"><small>scope</small><strong>{streamBacked ? 'observed_slice' : 'degraded'}</strong></div>
          <div className="telemetry-status-item"><small>last updated</small><strong>{formatTelemetryFreshness(collection?.newest_sample_timestamp_seen)}</strong></div>
        </div>
      </div>

      {loading ? <Card title="Product / Engineering"><div className="state-message">Loading telemetry analytics…</div></Card> : null}
      {error ? <Card title="Product / Engineering Error"><div className="state-message error">{error}</div></Card> : null}

      {!loading && !error ? (
        <>
          <Card title="Board framing">
            <div className="telemetry-board-summary">
              <div className="list-item status-neutral">
                <strong>Layout rule</strong>
                <p>Each telemetry section is now one full-width row with 5 fixed columns: UI Component, Data Source / Backend Field, KPI / Derived Metric, Truth / Sample Context, and Action / Drill-down.</p>
              </div>
              <div className="list-item status-muted">
                <strong>Sample scope</strong>
                <p>{sampleScope}</p>
              </div>
              <div className={`list-item status-${streamBacked ? 'warn' : 'bad'}`}>
                <strong>Guardrail</strong>
                <p>{blockedStates.generalization.decision_blocked}</p>
                <small><strong>missing source:</strong> {blockedStates.generalization.missing_source}</small>
                <small><strong>next action:</strong> {blockedStates.generalization.required_action_to_unblock}</small>
              </div>
            </div>
          </Card>

          {groupedRows.map((group) => (
            <div className="telemetry-board-section" key={group.title}>
              <div className="telemetry-board-section-head">
                <h3>{group.title}</h3>
                <small>{group.rows.length} rows</small>
              </div>
              <div className="telemetry-board-stack">
                {group.rows.map((row) => <BoardRow key={row.id} row={row} />)}
              </div>
            </div>
          ))}
        </>
      ) : null}
    </div>
  )
}
