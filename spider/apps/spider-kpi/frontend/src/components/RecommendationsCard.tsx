import { useEffect, useState } from 'react'

/**
 * Action Recommendations card.
 *
 * Drops on every division page and surfaces the "what to do next"
 * items the recommendations engine generated for that division. The
 * goal is to turn the dashboard from "displays data" into "tells you
 * what to do" without bolting on an AI agent.
 *
 * Each item has a severity (critical/warn/info), the data point that
 * triggered it, the suggested action as a verb phrase, and the
 * impact estimate if the action is taken.
 *
 * If the engine returns 0 items, the card collapses to a single
 * green "All clear — no actions needed for this division" line.
 */

type Severity = 'critical' | 'warn' | 'info'

interface Recommendation {
  title: string
  severity: Severity
  evidence: string
  action: string
  impact: string
  key: string
}

interface RecommendationsResponse {
  generated_at: string
  division: string
  count: number
  by_severity: { critical: number; warn: number; info: number }
  recommendations: Recommendation[]
}

const SEVERITY_COLOR: Record<Severity, string> = {
  critical: 'var(--red)',
  warn: 'var(--orange)',
  info: 'var(--blue)',
}

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'CRITICAL',
  warn: 'WARN',
  info: 'INFO',
}

export interface RecommendationsCardProps {
  division: 'pe' | 'cx' | 'marketing' | 'operations' | 'firmware'
}

const DIVISION_LABEL: Record<RecommendationsCardProps['division'], string> = {
  pe: 'Product Engineering',
  cx: 'Customer Experience',
  marketing: 'Marketing',
  operations: 'Operations',
  firmware: 'Firmware',
}

export function RecommendationsCard({ division }: RecommendationsCardProps) {
  const [data, setData] = useState<RecommendationsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const ctl = new AbortController()
    fetch(`/api/recommendations/${division}`, { signal: ctl.signal, credentials: 'include' })
      .then(async r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => setData(d as RecommendationsResponse))
      .catch(err => { if (err.name !== 'AbortError') setError(String(err.message || err)) })
    return () => ctl.abort()
  }, [division])

  if (error) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>
          Recommendations engine unavailable: {error}
        </div>
      </section>
    )
  }
  if (!data) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--muted)' }}>
        <div style={{ fontSize: 11, color: 'var(--muted)' }}>Loading recommendations…</div>
      </section>
    )
  }

  if (data.recommendations.length === 0) {
    return (
      <section className="card" style={{ borderLeft: '3px solid var(--green)', padding: '10px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontSize: 13 }}>
          <strong style={{ color: 'var(--green)' }}>✓ All clear.</strong>
          <span style={{ color: 'var(--muted)' }}>
            No prioritized actions for {DIVISION_LABEL[division]} right now.
          </span>
        </div>
      </section>
    )
  }

  const topSeverity = data.recommendations[0]?.severity ?? 'info'

  return (
    <section className="card" style={{ borderLeft: `3px solid ${SEVERITY_COLOR[topSeverity]}` }}>
      <div className="venom-panel-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <strong>What to do next — {DIVISION_LABEL[division]}</strong>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
            Prioritized actions generated from current data. Critical first, then warn, then info.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, fontSize: 11 }}>
          {(['critical', 'warn', 'info'] as Severity[]).map(s => {
            const n = data.by_severity[s]
            if (!n) return null
            return (
              <span key={s} style={{
                padding: '2px 8px',
                borderRadius: 10,
                background: 'var(--panel-2)',
                color: SEVERITY_COLOR[s],
                fontWeight: 600,
              }}>
                {SEVERITY_LABEL[s]} {n}
              </span>
            )
          })}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
        {data.recommendations.map(r => (
          <div key={r.key} style={{
            padding: 10,
            background: 'var(--panel-2)',
            borderRadius: 6,
            borderLeft: `3px solid ${SEVERITY_COLOR[r.severity]}`,
          }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10 }}>
              <strong style={{ fontSize: 13 }}>{r.title}</strong>
              <span style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1,
                color: SEVERITY_COLOR[r.severity],
              }}>
                {SEVERITY_LABEL[r.severity]}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              <strong>Evidence:</strong> {r.evidence}
            </div>
            <div style={{ fontSize: 12, marginTop: 6 }}>
              <strong>Action:</strong> {r.action}
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
              <strong>Impact:</strong> {r.impact}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
