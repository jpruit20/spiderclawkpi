import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { currency, impactFromConversion } from '../lib/operatingModel'
import { DiagnosticItem, RecommendationItem, SourceHealthItem } from '../lib/types'

function scoreConfidence(diagnostic: DiagnosticItem, sourceHealth: SourceHealthItem[]) {
  const health = sourceHealth.filter((row) => ['shopify','triplewhale','freshdesk','clarity','ga4'].includes(row.source) && row.derived_status === 'healthy').length / 5
  return Number((((diagnostic.confidence || 0.5) * 0.7) + (health * 0.3)).toFixed(2))
}

export function RootCause() {
  const [diagnostics, setDiagnostics] = useState<DiagnosticItem[]>([])
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([])
  const [sourceHealth, setSourceHealth] = useState<SourceHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [diagPayload, recPayload, sourcePayload, overviewPayload] = await Promise.all([api.diagnostics(), api.recommendations(), api.sourceHealth(), api.overview()])
        if (cancelled) return
        const latest = overviewPayload.latest_kpi
        const rows = diagPayload.map((item) => {
          const sessions = Number(latest?.sessions || 0)
          const aov = Number(latest?.average_order_value || 0)
          const conversionChange = Math.abs(Number(item.details_json?.conversion_change_pct || 0))
          const impact = impactFromConversion(sessions, Math.max(0.1, conversionChange * 0.1), aov) * 7
          return { ...item, impact, confidenceDisplay: scoreConfidence(item, sourcePayload) }
        }).sort((a, b) => b.impact - a.impact)
        setDiagnostics(rows)
        setRecommendations(recPayload)
        setSourceHealth(sourcePayload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load root cause')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [])

  const top = diagnostics[0]
  const topRecommendation = useMemo(() => recommendations.find((item) => item.owner_team === top?.owner_team) || recommendations[0], [recommendations, top])

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Root Cause</h2>
        <p>Condense evidence into one cause, one owner, one action, and one revenue estimate.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Root Cause"><div className="state-message">Loading root cause evidence…</div></Card> : null}
      {error ? <Card title="Root Cause Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="three-col">
            <Card title="Primary Cause"><div className="hero-metric">{top ? top.title : '—'}</div><div className="state-message">Highest-impact explanation currently available</div></Card>
            <Card title="Weekly Impact"><div className="hero-metric">{top ? currency((top as any).impact) : '$0'}</div><div className="state-message">Estimated from conversion drag × sessions × AOV</div></Card>
            <Card title="Confidence"><div className="hero-metric">{top ? (top as any).confidenceDisplay.toFixed(2) : '0.00'}</div><div className="state-message">Data quality + evidence confidence combined</div></Card>
          </div>
          <div className="two-col two-col-equal">
            <Card title="Primary Root Cause">
              {top ? (
                <div className="stack-list compact">
                  <div className="list-item"><strong>Cause</strong><p>{top.root_cause || top.summary}</p></div>
                  <div className="list-item"><strong>Owner</strong><p>{top.owner_team || 'TBD'}</p></div>
                  <div className="list-item"><strong>SLA</strong><p>48h</p></div>
                </div>
              ) : <div className="state-message">No diagnostics returned.</div>}
            </Card>
            <Card title="Best next action">
              {topRecommendation ? (
                <div className="stack-list compact">
                  <div className="list-item"><strong>{topRecommendation.title}</strong><p>{topRecommendation.recommended_action}</p></div>
                  <div className="list-item"><strong>Estimated impact</strong><p>{topRecommendation.estimated_impact || (top ? `${currency((top as any).impact)}/week` : '$0/week')}</p></div>
                </div>
              ) : <div className="state-message">No recommendation returned.</div>}
            </Card>
          </div>
          <Card title="Root Cause Queue">
            <div className="stack-list">
              {diagnostics.map((item: any) => (
                <div className={`list-item status-${item.severity === 'high' ? 'bad' : item.severity === 'medium' ? 'warn' : 'good'}`} key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className="badge badge-good">{currency(item.impact)}/week</span>
                      <span className="badge badge-neutral">confidence {item.confidenceDisplay.toFixed(2)}</span>
                    </div>
                  </div>
                  <p>{item.summary}</p>
                  <small>Owner {item.owner_team || 'TBD'} · root cause {item.root_cause || 'n/a'}</small>
                </div>
              ))}
            </div>
          </Card>
        </>
      ) : null}
    </div>
  )
}
