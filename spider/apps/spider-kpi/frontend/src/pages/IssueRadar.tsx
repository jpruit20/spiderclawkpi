import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { currency } from '../lib/operatingModel'
import { IssueClusterItem, IssueRadarResponse } from '../lib/types'

function ClusterList({ title, rows, mode = 'queue' }: { title: string; rows: IssueClusterItem[]; mode?: 'queue' | 'evidence' }) {
  return (
    <Card title={title}>
      <div className="stack-list">
        {rows.map((item) => (
          <div className={`list-item status-${item.severity === 'high' ? 'bad' : item.severity === 'medium' ? 'warn' : 'good'}`} key={`${title}-${item.id}`}>
            <div className="item-head">
              <strong>{item.title}</strong>
              <span className={`badge severity-${item.severity}`}>{item.severity}</span>
            </div>
            <p>{String(item.details_json?.priority_reason_summary || 'No priority reason')}</p>
            <small>
              Queue rank #{String(item.details_json?.priority_rank ?? 'n/a')} · Score {String(item.details_json?.priority_score ?? 'n/a')} · Burden{' '}
              {String(item.details_json?.tickets_per_100_orders_by_theme ?? 'n/a')} / 100 orders · Trend {String(item.details_json?.trend_label ?? 'n/a')}
            </small>
            <small>Estimated weekly impact {currency(Number(item.details_json?.priority_score || 0) * 12)}</small>
            <small>
              {mode === 'queue' ? 'Escalation target' : 'Supporting evidence'}: {Array.isArray(item.details_json?.impact_type) ? item.details_json.impact_type.join(', ') : String(item.details_json?.impact_type ?? 'n/a')} · Owner: {item.owner_team || 'TBD'}
            </small>
          </div>
        ))}
        {!rows.length ? <div className="state-message">No rows returned.</div> : null}
      </div>
    </Card>
  )
}

export function IssueRadar() {
  const [data, setData] = useState<IssueRadarResponse>({
    signals: [],
    clusters: [],
    highest_business_risk: [],
    highest_burden: [],
    fastest_rising: [],
    source_breakdown: [],
    trend_heatmap: [],
    live_sources: [],
    scaffolded_sources: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const payload = await api.issues()
        if (!cancelled) setData(payload)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load issues')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const sortedClusters = useMemo(
    () => [...data.clusters].sort((a, b) => Number(b.details_json?.priority_score || 0) - Number(a.details_json?.priority_score || 0)),
    [data.clusters],
  )
  const topThree = sortedClusters.slice(0, 3)
  const actionItems = [
    topThree[0] ? `Escalate now: ${topThree[0].title}. ${String(topThree[0].details_json?.priority_reason_summary || '')}` : 'No priority cluster returned yet; verify connector health and issue normalization.',
    data.fastest_rising[0] ? `Watch next: ${data.fastest_rising[0].title}. Confirm whether the rise reflects a new product, fulfillment, or support workflow issue.` : 'No rising cluster yet; keep reviewing complaint burden and business risk instead of chasing noise.',
    data.live_sources.length ? `Radar queue currently draws from live sources: ${data.live_sources.join(', ')}.` : 'Issue radar still needs more live source coverage before it can serve as the primary voice-of-customer queue.',
  ]

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Issue Radar</h2>
        <p>Emerging and escalated issue queue. This page answers what needs escalation, not why it happened.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {!loading && !error ? (
        <div className="three-col">
          <Card title="Priority Queue"><div className="hero-metric">{sortedClusters.length}</div><div className="state-message">Issue clusters ranked for escalation</div></Card>
          <Card title="Live Sources"><div className="hero-metric">{data.live_sources.length}</div><div className="state-message">Live inputs currently feeding issue analysis</div></Card>
          <Card title="Fastest Rising"><div className="hero-metric">{data.fastest_rising.length}</div><div className="state-message">Clusters with active upward pressure</div></Card>
        </div>
      ) : null}
      <ActionBlock title="Issue Queue Actions" items={actionItems} />
      {loading ? <Card title="Issue Radar Status"><div className="state-message">Loading live issue data…</div></Card> : null}
      {error ? <Card title="Issue Radar Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <div className="two-col two-col-equal">
            <Card title="Radar Role">
              <div className="stack-list compact">
                <div className="list-item status-good"><strong>Question answered</strong><p>What issue should the operator queue escalate first?</p></div>
                <div className="list-item status-warn"><strong>Not this page</strong><p>Root-cause adjudication, intervention design, and evidence synthesis belong in Root Cause.</p></div>
              </div>
            </Card>
            <Card title="Escalation logic">
              <div className="stack-list compact">
                <div className="list-item status-muted"><strong>Ranked by</strong><p>Priority score, complaint burden, business-risk weighting, and trend acceleration.</p></div>
                <div className="list-item status-muted"><strong>Hand-off</strong><p>Once a queue item is accepted, Root Cause should determine explanation, owner, and intervention framing.</p></div>
                <div className="list-item status-muted"><strong>Drill-downs</strong><p><a href="/root-cause">View root cause</a> · <a href="/friction">View friction details</a></p></div>
              </div>
            </Card>
          </div>
          <ClusterList title="Escalate First" rows={topThree} mode="queue" />
          <div className="two-col">
            <ClusterList title="Watchlist: Fastest Rising" rows={data.fastest_rising.slice(0, 3)} mode="queue" />
            <ClusterList title="Evidence: Highest Complaint Burden" rows={data.highest_burden.slice(0, 3)} mode="evidence" />
          </div>
          <div className="two-col">
            <Card title="Issue Signals">
              <div className="stack-list">
                {data.signals.map((item) => (
                  <div className={`list-item status-${item.severity === 'high' ? 'bad' : item.severity === 'medium' ? 'warn' : 'good'}`} key={item.id}>
                    <div className="item-head">
                      <strong>{item.title}</strong>
                      <span className={`badge severity-${item.severity}`}>{item.severity}</span>
                    </div>
                    <p>{item.summary}</p>
                    <small>
                      Source: {item.source} · Queue rank #{String(item.metadata_json?.priority_rank ?? 'n/a')} · Trend {String(item.metadata_json?.trend_label ?? 'n/a')} · Burden {String(item.metadata_json?.tickets_per_100_orders ?? 'n/a')} / 100 orders
                    </small>
                    <small>{String(item.metadata_json?.priority_reason_summary ?? 'No priority reason')}</small>
                  </div>
                ))}
                {!data.signals.length ? <div className="state-message">No issue signals returned.</div> : null}
              </div>
            </Card>
            <Card title="Source Breakdown">
              <div className="stack-list">
                {data.source_breakdown.map((item) => (
                  <div className={`list-item ${item.live ? 'live-source' : 'scaffold-source'}`} key={item.source}>
                    <div className="item-head">
                      <strong>{item.source}</strong>
                      <span className={`badge ${item.live ? 'badge-good' : 'badge-muted'}`}>{item.live ? 'Live' : 'Scaffolded'}</span>
                    </div>
                    <p>Signals: {item.signals} · Clusters: {item.clusters}</p>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  )
}
