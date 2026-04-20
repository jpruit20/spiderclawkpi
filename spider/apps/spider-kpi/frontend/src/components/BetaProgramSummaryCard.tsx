import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type BetaProgramSummary } from '../lib/api'

/**
 * Compact Firmware Beta program rollup for the Executive + Overview
 * pages. Lives on `/api/beta/summary` — active releases, cohort state
 * totals, and per-release post-deploy verdict tallies for the five most
 * recent releases. Intentionally spartan: operators drill into the
 * Product Engineering page for the full taxonomy / candidate UI.
 */

const STATE_COLORS: Record<string, string> = {
  invited: '#6b7280',
  opted_in: '#6ea8ff',
  ota_pushed: '#f59e0b',
  ota_confirmed: '#8b5cf6',
  evaluated: '#22c55e',
  declined: '#ef4444',
  expired: '#4b5563',
}

const HEALTH_COLORS: Record<string, string> = {
  resolved: '#22c55e',
  mixed: '#f59e0b',
  regression: '#ef4444',
  insufficient_data: '#6b7280',
}

export function BetaProgramSummaryCard() {
  const [data, setData] = useState<BetaProgramSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    api.betaSummary(ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if ((e as { name?: string }).name !== 'AbortError') {
          setError(e instanceof Error ? e.message : String(e))
        }
      })
    return () => ctrl.abort()
  }, [])

  if (error) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware Beta program</strong></div>
        <div className="state-message" style={{ color: 'var(--red)' }}>Error: {error}</div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card">
        <div className="venom-panel-head"><strong>Firmware Beta program</strong></div>
        <div className="state-message">Loading…</div>
      </section>
    )
  }

  const cohortEntries = Object.entries(data.cohort_states).sort((a, b) => b[1] - a[1])
  const cohortTotal = cohortEntries.reduce((a, [, n]) => a + n, 0)

  return (
    <section className="card">
      <div className="venom-panel-head">
        <div>
          <strong>Firmware Beta program</strong>
          <p className="venom-chart-sub">
            {data.active_releases} active / {data.total_releases} total release{data.total_releases === 1 ? '' : 's'} · {cohortTotal} device{cohortTotal === 1 ? '' : 's'} in cohorts.
          </p>
        </div>
        <Link to="/division/product-engineering" className="btn-secondary" style={{ fontSize: 11 }}>
          Manage →
        </Link>
      </div>

      {cohortEntries.length > 0 && (
        <div style={{ display: 'flex', height: 18, borderRadius: 6, overflow: 'hidden', marginBottom: 12 }}>
          {cohortEntries.map(([state, n]) => (
            <div
              key={state}
              title={`${state}: ${n}`}
              style={{
                flex: n, background: STATE_COLORS[state] ?? '#555',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontSize: 9, fontWeight: 600,
              }}
            >{n}</div>
          ))}
        </div>
      )}

      {data.recent.length === 0 ? (
        <div className="state-message">No firmware releases yet.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table">
            <thead><tr>
              <th>Release</th><th>Status</th><th>Addresses</th><th>Health</th><th>Verdict tally</th>
            </tr></thead>
            <tbody>
              {data.recent.map(r => {
                const tally = r.tally || {}
                const tallyEntries = Object.entries(tally).filter(([, n]) => n > 0)
                return (
                  <tr key={r.id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}><strong>{r.version}</strong></td>
                    <td style={{ fontSize: 11, color: 'var(--muted)' }}>{r.status}</td>
                    <td style={{ fontSize: 11 }}>{r.addresses_issues.join(', ') || '—'}</td>
                    <td>
                      {r.release_health ? (
                        <span style={{
                          padding: '2px 6px', borderRadius: 8,
                          background: (HEALTH_COLORS[r.release_health] ?? '#555') + '33',
                          color: HEALTH_COLORS[r.release_health] ?? '#fff',
                          fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600,
                        }}>{r.release_health}</span>
                      ) : <span style={{ fontSize: 11, color: 'var(--muted)' }}>—</span>}
                    </td>
                    <td style={{ fontSize: 11 }}>
                      {tallyEntries.length === 0
                        ? <span style={{ color: 'var(--muted)' }}>—</span>
                        : tallyEntries.map(([k, n]) => `${k}: ${n}`).join(' · ')}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
