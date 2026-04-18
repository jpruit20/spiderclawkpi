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

  const chartData = cohorts.map(c => ({
    firmware: c.firmware_version,
    success_pct: Number((c.success_rate * 100).toFixed(1)),
    error_pct: Number((c.error_session_rate * 100).toFixed(1)),
    sessions: c.sessions,
    avg_stability: c.avg_stability,
    avg_duration_min: Math.round(c.avg_duration_seconds / 60),
    avg_tts_seconds: c.avg_tts_seconds,
  }))

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware cohort performance</strong>
          <p className="venom-chart-sub">
            Cook-success and error-session rate per firmware (n ≥ {resp.min_sessions_threshold}).
            Baseline benchmark: {(COOK_SUCCESS_BENCHMARK * 100).toFixed(0)}% median success across 28 months.
          </p>
        </div>
        <span className="venom-panel-hint">{resp.total_sessions.toLocaleString()} total sessions</span>
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={Math.max(220, cohorts.length * 26 + 60)}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis type="number" domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} stroke="#9fb0d4" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="firmware" stroke="#9fb0d4" tick={{ fontSize: 11 }} width={110} />
            <Tooltip
              contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 12 }}
              formatter={(v: number, name: string) => [`${v}%`, name]}
            />
            <ReferenceLine x={COOK_SUCCESS_BENCHMARK * 100} stroke="rgba(34, 197, 94, 0.5)" strokeDasharray="3 3" label={{ value: '69% median', position: 'top', fill: 'rgba(34, 197, 94, 0.9)', fontSize: 10 }} />
            <Bar name="Cook success %" dataKey="success_pct" fill="rgba(34, 197, 94, 0.6)">
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.success_pct >= 73 ? '#22c55e' : d.success_pct >= 65 ? '#4ade80' : d.success_pct >= 55 ? '#f59e0b' : '#ef4444'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: 'var(--muted)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              <th style={{ textAlign: 'left', padding: '4px 6px' }}>Firmware</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Sessions</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Success</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Errors</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Stability</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Avg dur</th>
              <th style={{ textAlign: 'right', padding: '4px 6px' }}>Avg TTS</th>
            </tr>
          </thead>
          <tbody>
            {cohorts.map(c => (
              <tr key={c.firmware_version} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <td style={{ padding: '4px 6px' }}><code>{c.firmware_version}</code></td>
                <td style={{ padding: '4px 6px', textAlign: 'right' }}>{c.sessions.toLocaleString()}</td>
                <td style={{ padding: '4px 6px', textAlign: 'right', color: c.success_rate >= 0.69 ? 'var(--green)' : 'var(--orange)' }}>
                  {(c.success_rate * 100).toFixed(1)}%
                </td>
                <td style={{ padding: '4px 6px', textAlign: 'right', color: c.error_session_rate <= 0.02 ? 'var(--green)' : c.error_session_rate <= 0.05 ? 'var(--orange)' : 'var(--red)' }}>
                  {(c.error_session_rate * 100).toFixed(1)}%
                </td>
                <td style={{ padding: '4px 6px', textAlign: 'right' }}>{c.avg_stability.toFixed(2)}</td>
                <td style={{ padding: '4px 6px', textAlign: 'right' }}>{Math.round(c.avg_duration_seconds / 60)}m</td>
                <td style={{ padding: '4px 6px', textAlign: 'right' }}>{c.avg_tts_seconds != null ? `${Math.round(c.avg_tts_seconds)}s` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
