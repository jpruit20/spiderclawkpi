import { useEffect, useMemo, useState } from 'react'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { IssueClusterItem, IssueRadarResponse } from '../lib/types'

function ClusterList({ title, rows }: { title: string; rows: IssueClusterItem[] }) {
  return (
    <Card title={title}>
      <div className="stack-list">
        {rows.map((item) => (
          <div className="list-item" key={`${title}-${item.id}`}>
            <div className="item-head">
              <strong>{item.title}</strong>
              <span className={`badge severity-${item.severity}`}>{item.severity}</span>
            </div>
            <p>{String(item.details_json?.priority_reason_summary || 'No priority reason')}</p>
            <small>
              Priority #{String(item.details_json?.priority_rank ?? 'n/a')} · Score {String(item.details_json?.priority_score ?? 'n/a')} · Burden{' '}
              {String(item.details_json?.tickets_per_100_orders_by_theme ?? 'n/a')} / 100 orders · Trend {String(item.details_json?.trend_label ?? 'n/a')}
            </small>
            <small>
              Impact: {Array.isArray(item.details_json?.impact_type) ? item.details_json.impact_type.join(', ') : String(item.details_json?.impact_type ?? 'n/a')} · Owner: {item.owner_team || 'TBD'}
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

  return (
    <div className="page-grid">
      <div className="page-head">
        <h2>Issue Radar</h2>
        <p>Priority-sorted issue intelligence with the top business risks called out explicitly.</p>
        <small className="page-meta">API base: {getApiBase()}</small>
      </div>
      {loading ? <Card title="Issue Radar Status"><div className="state-message">Loading live issue data…</div></Card> : null}
      {error ? <Card title="Issue Radar Error"><div className="state-message error">{error}</div></Card> : null}
      {!loading && !error ? (
        <>
          <ClusterList title="Highest Business Risk" rows={topThree} />
          <div className="two-col">
            <ClusterList title="Fastest Rising" rows={data.fastest_rising} />
            <ClusterList title="Highest Complaint Burden" rows={data.highest_burden} />
          </div>
          <Card title="All Priority-Sorted Clusters">
            <div className="stack-list">
              {sortedClusters.map((item) => (
                <div className="list-item" key={item.id}>
                  <div className="item-head">
                    <strong>{item.title}</strong>
                    <div className="inline-badges">
                      <span className={`badge severity-${item.severity}`}>{item.severity}</span>
                      <span className="badge badge-neutral">Priority {String(item.details_json?.priority_rank ?? 'n/a')}</span>
                    </div>
                  </div>
                  <p>{String(item.details_json?.priority_reason_summary || 'No priority reason')}</p>
                  <small>Tickets / 100 orders: {String(item.details_json?.tickets_per_100_orders_by_theme ?? 'n/a')} · Priority score: {String(item.details_json?.priority_score ?? 'n/a')}</small>
                  <small>Impact type: {Array.isArray(item.details_json?.impact_type) ? item.details_json.impact_type.join(', ') : String(item.details_json?.impact_type ?? 'n/a')} · Trend: {String(item.details_json?.trend_label ?? 'n/a')}</small>
                </div>
              ))}
              {!sortedClusters.length ? <div className="state-message">No clusters returned.</div> : null}
            </div>
          </Card>
          <div className="two-col">
            <Card title="Issue Signals">
              <div className="stack-list">
                {data.signals.map((item) => (
                  <div className="list-item" key={item.id}>
                    <div className="item-head">
                      <strong>{item.title}</strong>
                      <span className={`badge severity-${item.severity}`}>{item.severity}</span>
                    </div>
                    <p>{item.summary}</p>
                    <small>
                      Source: {item.source} · Priority #{String(item.metadata_json?.priority_rank ?? 'n/a')} · Trend {String(item.metadata_json?.trend_label ?? 'n/a')} · Burden {String(item.metadata_json?.tickets_per_100_orders ?? 'n/a')} / 100 orders
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
