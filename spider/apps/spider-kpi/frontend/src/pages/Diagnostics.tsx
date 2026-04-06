import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { ApiError, api } from '../lib/api'
import { DiagnosticItem, RecommendationItem } from '../lib/types'

export function DiagnosticsPage() {
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([])
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [diagnosticsPayload, recommendationsPayload] = await Promise.all([
          api.diagnostics(),
          api.recommendations(),
        ])
        if (!cancelled) {
          setDiagnostics(diagnosticsPayload)
          setRecommendations(recommendationsPayload)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load diagnostics')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const actionItems = useMemo(() => [
    recommendations[0]?.recommended_action || 'No recommendation returned; inspect top diagnostics and source health before acting.',
    diagnostics[0]?.root_cause ? `Highest-confidence root cause: ${diagnostics[0].root_cause}` : 'Root cause confidence is thin; widen the evidence set before committing changes.',
    diagnostics[0]?.owner_team ? `Primary owner should be ${diagnostics[0].owner_team}.` : 'No owner tagged; assign clear operational ownership before remediation.',
  ], [diagnostics, recommendations])

  const highSeverityCount = diagnostics.filter((item) => item.severity === 'high').length
  const assignedCount = diagnostics.filter((item) => item.owner_team).length

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Diagnostics</h2>
        <p>What changed, why it changed, what to fix, and who should own it.</p>
      </div>
      {!loading && !error ? (
        <div className="three-col">
          <Card title="Priority Diagnostics"><div className="hero-metric">{diagnostics.length}</div><div className="state-message">Evidence items currently surfaced</div></Card>
          <Card title="High Severity"><div className="hero-metric">{highSeverityCount}</div><div className="state-message">Items marked high severity</div></Card>
          <Card title="Ownership Tagged"><div className="hero-metric">{assignedCount}/{diagnostics.length || 0}</div><div className="state-message">Diagnostics with an owner team assigned</div></Card>
        </div>
      ) : null}
      <ActionBlock items={actionItems} />
      {loading ? <Card title="Diagnostics Status"><div className="state-message">Loading live diagnostics…</div></Card> : null}
      {error ? <Card title="Diagnostics Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <div className="two-col">
          <Card title="Driver Diagnostics">
            <div className="stack-list">
              {diagnostics.map((item) => (
                <div className={`list-item status-${item.severity === 'high' ? 'bad' : item.severity === 'medium' ? 'warn' : 'good'}`} key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge severity-${item.severity}`}>{item.severity}</span>
                      <span className="badge badge-neutral">{item.business_date}</span>
                    </div>
                  </div>
                  <p>{item.summary}</p>
                  <small>Root cause: {item.root_cause || 'n/a'} · Owner: {item.owner_team || 'TBD'} · Confidence: {item.confidence}</small>
                  <small>
                    Traffic Δ: {String(item.details_json?.sessions_change_pct ?? 'n/a')}% ·
                    Conversion Δ: {String(item.details_json?.conversion_change_pct ?? 'n/a')}% ·
                    AOV Δ: {String(item.details_json?.aov_change_pct ?? 'n/a')}%
                  </small>
                  {item.details_json?.issue_link ? (
                    <div className="state-message">
                      <strong>Issue-linked evidence:</strong> Issue Radar overrode the generic root cause because
                      {' '}{String((item.details_json.issue_link as any).theme)} is
                      {' '}{String((item.details_json.issue_link as any).trend_label)} and still has burden
                      {' '}{String((item.details_json.issue_link as any).tickets_per_100_orders_by_theme ?? (item.details_json.issue_link as any).tickets_per_100_orders ?? 'n/a')}
                      {' '}per 100 orders, with priority rank
                      {' '}{String((item.details_json.issue_link as any).priority_rank ?? 'n/a')}.
                    </div>
                  ) : null}
                </div>
              ))}
              {!diagnostics.length ? <div className="state-message">No diagnostics returned.</div> : null}
            </div>
          </Card>
          <Card title="Recommended Actions">
            <div className="stack-list">
              {recommendations.map((item) => (
                <div className={`list-item status-${item.severity === 'high' ? 'bad' : item.severity === 'medium' ? 'warn' : 'good'}`} key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <span className={`badge severity-${item.severity}`}>{item.severity}</span>
                  </div>
                  <p>{item.recommended_action}</p>
                  <small>{item.owner_team} · Severity: {item.severity}</small>
                </div>
              ))}
              {!recommendations.length ? <div className="state-message">No recommendations returned.</div> : null}
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  )
}
