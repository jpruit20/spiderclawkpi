import { useEffect, useState } from 'react'
import { BarChart, Bar, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'
import type { FirmwareCohort, FirmwareCohortsResponse } from '../lib/types'

/**
 * Firmware cohort session performance — cook-success rate and
 * error-session rate per firmware version, with n ≥ threshold.
 *
 * Shipping blocked until v2 S3 backfill populates telemetry_sessions.
 * Until then the API returns ok=false with a hint; we show that hint
 * so the page isn't empty. Once sessions land, this lights up without
 * a code change.
 *
 * The Jan 2026 → Feb 2026 01.01.94 rollback (2.4M events → 3,312) is
 * the canonical use-case for this panel; once session data exists for
 * the 01.01.94 window we'll see its success rate vs. 01.01.97 directly.
 */

const COOK_SUCCESS_BENCHMARK = 0.69  // 28-month median, from the comprehensive report

export function FirmwareCohortPanel({ minSessions = 20 }: { minSessions?: number }) {
  const [resp, setResp] = useState<FirmwareCohortsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.firmwareCohorts(minSessions)
      .then(r => { if (!cancelled) setResp(r) })
      .catch(() => { /* silent — absence doesn't break page */ })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [minSessions])

  if (loading) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware cohort performance</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  if (!resp || !resp.ok) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--orange)' }}>
        <div className="venom-panel-head">
          <strong>Firmware cohort performance</strong>
          <span className="venom-panel-hint">
            {resp ? `${resp.total_sessions} sessions so far` : 'waiting on data'}
          </span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          {resp?.hint || 'Session-level data not yet available. This panel populates automatically once the v2 S3 backfill completes.'}
        </p>
      </section>
    )
  }

  const cohorts: FirmwareCohort[] = resp.cohorts || []
  if (cohorts.length === 0) {
    return (
      <section className="card">
        <div className="venom-panel-head">
          <strong>Firmware cohort performance</strong>
          <span className="venom-panel-hint">{resp.total_sessions} sessions · no cohorts ≥ {resp.min_sessions_threshold}</span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>
          Session data is present but no firmware version has enough sessions (threshold: {resp.min_sessions_threshold}) to meaningfully compare yet.
        </p>
      </section>
    )
  }

  // Prefer new-model held_target_rate when populated. Fall back to legacy
  // success_rate so the card still renders useful info during re-derivation.
  const hasNewModel = cohorts.some(c => c.held_target_rate != null)
  const headlineMetricFor = (c: typeof cohorts[number]): number =>
    hasNewModel && c.held_target_rate != null ? c.held_target_rate : c.success_rate

  const chartData = cohorts.map(c => ({
    firmware: c.firmware_version,
    headline_pct: Number((headlineMetricFor(c) * 100).toFixed(1)),
    in_control_pct: c.avg_in_control_pct != null ? Number((c.avg_in_control_pct * 100).toFixed(1)) : null,
    error_pct: Number((c.error_session_rate * 100).toFixed(1)),
    sessions: c.sessions,
    avg_duration_min: Math.round(c.avg_duration_seconds / 60),
    avg_tts_seconds: c.avg_tts_seconds,
  }))

  const headlineLabel = hasNewModel ? 'Held-target rate' : 'Cook success (legacy)'
  const benchmarkLabel = hasNewModel ? 'target 75%' : '69% median'
  const benchmark = hasNewModel ? 0.75 : COOK_SUCCESS_BENCHMARK

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware cohort performance</strong>
          <p className="venom-chart-sub">
            {hasNewModel ? (
              <>
                <strong>Held-target rate</strong> per firmware (n ≥ {resp.min_sessions_threshold} sessions).
                Excludes startup-assist + disconnect sessions from the denominator.
                Secondary: in-control % (PID quality during non-disturbance windows).
              </>
            ) : (
              <>
                Legacy cook-success rate per firmware (n ≥ {resp.min_sessions_threshold}).
                Intent/outcome model columns not yet populated — baseline benchmark: {(COOK_SUCCESS_BENCHMARK * 100).toFixed(0)}%.
              </>
            )}
          </p>
        </div>
        <span className="venom-panel-hint">{resp.total_sessions.toLocaleString()} total sessions</span>
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={Math.max(240, cohorts.length * 28 + 60)}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis type="number" domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} stroke="#9fb0d4" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="firmware" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={110} />
            <Tooltip
              contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
              formatter={(v: number, name: string) => [v != null ? `${v}%` : '—', name]}
            />
            <ReferenceLine x={benchmark * 100} stroke="rgba(34, 197, 94, 0.5)" strokeDasharray="3 3" label={{ value: benchmarkLabel, position: 'top', fill: 'rgba(34, 197, 94, 0.9)', fontSize: 10 }} />
            <Bar name={headlineLabel} dataKey="headline_pct" fill="rgba(34, 197, 94, 0.6)">
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.headline_pct >= 78 ? '#22c55e' : d.headline_pct >= 70 ? '#4ade80' : d.headline_pct >= 60 ? '#f59e0b' : '#ef4444'} />
              ))}
            </Bar>
            {hasNewModel && (
              <Bar name="In-control %" dataKey="in_control_pct" fill="rgba(74, 122, 255, 0.35)" />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              <th style={{ textAlign: 'left', padding: '4px 6px' }}>Firmware</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Sessions</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }} title={hasNewModel ? 'Held-target rate: target reached and held within ±15°F for the required duration threshold. Denominator excludes startup-assist and disconnect sessions.' : 'Legacy cook success rate'}>
                {hasNewModel ? 'Held-target' : 'Success (legacy)'}
              </th>
              {hasNewModel && (
                <th style={{ textAlign: 'right', padding: '4px 6px' }} title="In-control %: fraction of post-reach, non-disturbance samples within ±15°F of target. Measures PID quality only during moments when the PID is in control — lid-open windows excluded.">
                  In-control
                </th>
              )}
              {hasNewModel && (
                <th style={{ textAlign: 'right', padding: '4px 6px' }} title="Avg disturbance events per cook. A disturbance is a ≥30°F rapid drop followed by recovery — a proxy for lid-opening.">
                  Disturb/cook
                </th>
              )}
              {hasNewModel && (
                <th style={{ textAlign: 'right', padding: '4px 6px' }} title="Avg seconds to return to ±15°F of target after a disturbance. Shorter = firmware PID recovers faster from lid-opens.">
                  Recovery
                </th>
              )}
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Errors</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Avg dur</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Avg TTS</th>
            </tr>
          </thead>
          <tbody>
            {cohorts.map(c => {
              const headline = headlineMetricFor(c)
              return (
                <tr key={c.firmware_version} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '4px 6px' }}><code>{c.firmware_version}</code></td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                    {c.sessions.toLocaleString()}
                    {hasNewModel && c.target_seeking_sessions > 0 && (
                      <span style={{ color: 'var(--muted)', marginLeft: 4, fontSize: 10 }}>
                        ({c.target_seeking_sessions} seeking)
                      </span>
                    )}
                  </td>
                  <td style={{ padding: '4px 6px', textAlign: 'right', color: headline >= 0.75 ? 'var(--green)' : headline >= 0.60 ? 'var(--orange)' : 'var(--red)' }}>
                    {(headline * 100).toFixed(1)}%
                  </td>
                  {hasNewModel && (
                    <td style={{ padding: '4px 6px', textAlign: 'right', color: c.avg_in_control_pct == null ? 'var(--muted)' : c.avg_in_control_pct >= 0.80 ? 'var(--green)' : c.avg_in_control_pct >= 0.65 ? 'var(--orange)' : 'var(--red)' }}>
                      {c.avg_in_control_pct != null ? `${(c.avg_in_control_pct * 100).toFixed(1)}%` : '—'}
                    </td>
                  )}
                  {hasNewModel && (
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>
                      {c.avg_disturbances_per_cook != null ? c.avg_disturbances_per_cook.toFixed(1) : '—'}
                    </td>
                  )}
                  {hasNewModel && (
                    <td style={{ padding: '4px 6px', textAlign: 'right', color: c.avg_recovery_seconds == null ? 'var(--muted)' : c.avg_recovery_seconds <= 180 ? 'var(--green)' : c.avg_recovery_seconds <= 300 ? 'var(--orange)' : 'var(--red)' }}>
                      {c.avg_recovery_seconds != null ? `${Math.round(c.avg_recovery_seconds)}s` : '—'}
                    </td>
                  )}
                  <td style={{ padding: '4px 6px', textAlign: 'right', color: c.error_session_rate <= 0.02 ? 'var(--green)' : c.error_session_rate <= 0.05 ? 'var(--orange)' : 'var(--red)' }}>
                    {(c.error_session_rate * 100).toFixed(1)}%
                  </td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}>{Math.round(c.avg_duration_seconds / 60)}m</td>
                  <td style={{ padding: '4px 6px', textAlign: 'right' }}>{c.avg_tts_seconds != null ? `${Math.round(c.avg_tts_seconds)}s` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {!hasNewModel && (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)', padding: '8px 12px', background: 'rgba(245,158,11,0.08)', borderLeft: '3px solid var(--orange)', borderRadius: 4 }}>
          <strong style={{ color: 'var(--orange)' }}>Pending re-derivation:</strong> the intent/outcome/PID-quality model
          columns are empty. The rederive_session_quality script will populate them once the S3 backfill finishes — this
          panel will automatically upgrade to the new metrics (held-target rate, in-control %, disturbance count,
          recovery time) without a code change.
        </div>
      )}
    </section>
  )
}
