import { useEffect, useMemo, useState } from 'react'
import { ActionBlock } from '../components/ActionBlock'
import { Card } from '../components/Card'
import { ApiError, api, getApiBase } from '../lib/api'
import { currency, frictionRankingScore } from '../lib/operatingModel'
import { ActionObject, BlockedStateOutput, IssueClusterItem, IssueRadarResponse, KPIObject, SourceHealthItem } from '../lib/types'
import { actionFromKpi, buildBlockedState, buildTextKpi, enforceActionContract, truthStateFromSource } from '../lib/divisionContract'

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
  const [sourceHealth, setSourceHealth] = useState<SourceHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [payload, sourcePayload] = await Promise.all([api.issues(), api.sourceHealth()])
        if (!cancelled) {
          setData(payload)
          setSourceHealth(sourcePayload)
        }
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

  const sortedClusters = useMemo(() => {
    return [...data.clusters]
      .map((item) => {
        const source = String(item.details_json?.source || '').toLowerCase()
        const usesClarity = source === 'clarity'
        const corroborated = Number(item.source_count || 0) > 1 || source !== 'clarity'
        const rankingScore = frictionRankingScore({
          impact: Number(item.details_json?.priority_score || 0) * 12,
          confidence: Number(item.confidence || 0.6),
          sourceHealth,
          usesClarity,
          corroborated,
        })
        return { ...item, __rankingScore: rankingScore }
      })
      .sort((a, b) => Number(b.__rankingScore || 0) - Number(a.__rankingScore || 0))
  }, [data.clusters, sourceHealth])
  const topThree = sortedClusters.slice(0, 3)
  const snapshotTimestamp = new Date().toISOString()
  const topIssueTruthState = truthStateFromSource(sourceHealth, ['freshdesk', 'clarity', 'ga4'], 'proxy')
  const kpis: KPIObject[] = [
    buildTextKpi({ key: 'issue_radar_top_issue', currentValue: topThree[0]?.title || 'No priority cluster returned yet', targetValue: 'No high-risk issue', owner: topThree[0]?.owner_team || 'TBD', status: topThree[0] ? 'red' : 'yellow', truthState: topIssueTruthState, lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'issue_radar_fastest_rising', currentValue: data.fastest_rising[0]?.title || 'No rising cluster', targetValue: 'No rising cluster', owner: data.fastest_rising[0]?.owner_team || 'TBD', status: data.fastest_rising[0] ? 'yellow' : 'green', truthState: topIssueTruthState, lastUpdated: snapshotTimestamp }),
    buildTextKpi({ key: 'issue_radar_source_coverage', currentValue: data.live_sources.length ? data.live_sources.join(', ') : 'Coverage incomplete', targetValue: 'Broad live coverage', owner: 'Joseph', status: data.live_sources.length ? 'yellow' : 'red', truthState: data.live_sources.length ? 'proxy' : 'blocked', lastUpdated: snapshotTimestamp }),
  ]
  const blockedStates: Record<string, BlockedStateOutput> = {
    issue_radar_source_coverage: buildBlockedState({
      decision_blocked: 'Whether issue radar can be treated as the primary escalation queue across all surfaces',
      missing_source: 'broader live source coverage',
      still_trustworthy: ['currently live sources', 'top visible issue clusters'],
      owner: 'Joseph',
      required_action_to_unblock: 'Increase live source coverage before treating queue gaps as true silence',
    }),
  }
  const actionItems: ActionObject[] = enforceActionContract([
    actionFromKpi({
      id: 'issue-radar-escalate-first',
      triggerKpi: kpis[0],
      triggerCondition: 'highest-business-risk cluster exists',
      owner: topThree[0]?.owner_team || 'TBD',
      requiredAction: topThree[0] ? `Escalate now: ${topThree[0].title}. ${String(topThree[0].details_json?.priority_reason_summary || '')}` : 'Verify connector health and issue normalization.',
      priority: 'critical',
      evidence: ['issue radar', 'freshdesk', 'clarity', 'ga4'],
      dueDate: '24h',
      snapshotTimestamp,
      baseRankingScore: Number(topThree[0]?.details_json?.priority_score || 75),
    }),
    actionFromKpi({
      id: 'issue-radar-watch-next',
      triggerKpi: kpis[1],
      triggerCondition: 'fastest-rising cluster exists',
      owner: data.fastest_rising[0]?.owner_team || 'TBD',
      requiredAction: data.fastest_rising[0] ? `Watch next: ${data.fastest_rising[0].title}. Confirm whether the rise reflects a new product, fulfillment, or support workflow issue.` : 'Keep reviewing complaint burden and business risk instead of chasing noise.',
      priority: 'high',
      evidence: ['issue radar'],
      dueDate: '48h',
      snapshotTimestamp,
      baseRankingScore: Number(data.fastest_rising[0]?.details_json?.priority_score || 50),
    }),
    actionFromKpi({
      id: 'issue-radar-unblock-coverage',
      triggerKpi: kpis[2],
      triggerCondition: 'truth_state = blocked',
      owner: 'Joseph',
      requiredAction: 'Unblock broader live source coverage before treating issue radar as complete.',
      priority: 'high',
      evidence: ['source breakdown'],
      dueDate: 'next source pass',
      snapshotTimestamp,
      baseRankingScore: 40,
      blockedState: blockedStates.issue_radar_source_coverage,
    }),
  ])

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
